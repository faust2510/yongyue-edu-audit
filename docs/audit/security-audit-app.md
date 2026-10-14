
# 应用与权限层安全审计（2026-09-18）

> 校长问题：「假如别人来偷资料偷数据，能保护得住吗？」
> 本篇回答**应用与权限层**（控制器 / 模型 ACL / ir.rule / 门户渲染 / 附件 / 凭据 / 登录注册面）。
> **服务器、网络、备份、TLS、防火墙、DB 账号**由另一名子代理负责，本篇不重复。

## 0. 审计边界与方法

| 项 | 内容 |
|---|---|
| 工作目录 | /Users/qwe/Documents/文件大总管/10-项目/教务系统网站新架构 |
| 本地环境 | docker compose（PG16 + odoo:19），DB edu19，http://localhost:8069 |
| 生产环境 | prod-host（马来西亚 203.0.113.10，/opt/edu-app，https://edu.example.org），DB edu19 |
| 代码清点 | AST 解析 custom_addons/edu_ 各模块 controllers 下全部 46 个控制器文件，逐条提取 http.route（含多路径路由） |
| 本地实测 | 4 个会话：匿名 / stu@local(uid 8) / parent@local(uid 10) / faculty@local(uid 11)；GET 只读 + 匿名无权限负向 POST |
| 生产探测 | 仅**只读 SELECT**（docker compose exec psql）与**只读 HTTP GET**；未做任何写操作 |
| 红线遵守 | ① 全程未修改任何业务数据、未创建账号、未落库；② 生产匿名意见箱（edu_feedback / edu_telegram 意见箱）**完全未触碰**；③ 越权探测一律 GET，未对他人的记录发起过写请求 |
| 未能验证 | 见文末「未验证项」——尤其是**生产环境未使用真实门户账号做越权实测**，该结论由「生产 ACL/ir.rule 与本地逐条比对一致」+「本地实测」共同支撑 |

## 1. 结论速览

| 指标 | 数量 |
|---|---|
| 清点 http.route 总数 | **257** |
| 其中 auth=user（须登录） | 217 |
| 其中 auth=public（匿名可访） | **39** |
| 其中 auth=none（无鉴权） | 1 |
| **有角色门禁**（先判身份/归属再拒绝） | 137 |
| 无独立门禁但**按当前身份收敛查询**（非本人得空集） | 47 |
| **完全无角色门禁** | **73**（user 40 / public 32 / none 1） |
| 其中人工复核后**确实能拿到非本人数据**的 | **2**（另有 2 条公开页泄露内部/PII 数据） |
| 越权实测命中（200 且返回数据） | **4 条**（详见第 3 节） |

**一句话结论**：门户控制器的「判空 + redirect」门禁**绝大多数是到位的**（137/257 显式门禁 + 47 条身份收敛），
真正的漏洞不在路由门禁，而在**模型层的行级权限（ir.rule）缺失**——门户账号拿到了整表读权限却没有行过滤，
一个 RPC 请求即可读走全校数据。这是本次审计最严重的发现。

---

## 2. 路由越权清点表（全量 257 条）

**逐模块条数**：edu_apply 2 ／ edu_brand 5 ／ edu_eval 6 ／ edu_life 10 ／ edu_portal 197 ／ edu_public 14 ／ edu_quiz 5 ／ edu_schedule 5 ／ edu_telegram 12 ／ edu_tg_bind 1。

> 表例：**type** http|json；**auth** user=须登录 / public=匿名可访 / none=无鉴权；**角色门禁**：`有` = 函数体内存在「先判身份或归属，再 redirect/404 拒绝」的分支；`收敛` = 无独立门禁，但查询按当前身份过滤（student.id / request.env.uid / partner_id），非本人得空集；`无` = 既无门禁也无身份收敛。**sudo** 字段：读=函数体内出现 sudo().search/browse/read_group，写=出现 sudo().create/write/unlink。

| 模块 | 路径 | type | auth | 角色门禁 | sudo | 视图方法 | 源文件:行 |
|---|---|---|---|---|---|---|---|
| edu_apply | `/apply` | http | public | 无 | — | apply_form | main.py:64 |
| edu_apply | `/apply/submit` | http | public | 无 | 读写 | apply_submit | main.py:69 |
| edu_brand | `/about` | http | public | 无 | — | about | main.py:12 |
| edu_brand | `/programs` | http | public | 无 | — | programs | main.py:16 |
| edu_brand | `/admissions` | http | public | 无 | — | admissions | main.py:20 |
| edu_brand | `/journal` | http | public | 无 | — | journal | main.py:24 |
| edu_brand | `/journal/page/<int:page_no>` | http | public | 无 | — | journal_page | main.py:34 |
| edu_eval | `/eval/fill/<int:task_id>` | http | user | 有 | 读 | eval_fill | eval_portal.py:83 |
| edu_eval | `/eval/fill/<int:task_id>/save` | http | user | 有 | 读 | eval_fill_save | eval_portal.py:108 |
| edu_eval | `/eval/my` | http | user | 无 | — | eval_my | eval_portal.py:161 |
| edu_eval | `/eval/review` | http | user | 收敛 | — | eval_review | eval_portal.py:195 |
| edu_eval | `/eval/review/<int:task_id>` | http | user | 有 | 读 | eval_review_form | eval_portal.py:261 |
| edu_eval | `/eval/review/<int:task_id>/submit` | http | user | 有 | 读 | eval_review_submit | eval_portal.py:286 |
| edu_life | `/my/checkins` | http | user | 无 | — | my_checkins | life.py:224 |
| edu_life | `/my/checkins/export` | http | user | 有 | 读 | my_checkins_export | life.py:231 |
| edu_life | `/my/checkins/check` | http | user | 有 | 读 | my_checkins_check | life.py:251 |
| edu_life | `/my/journals` | http | user | 有 | — | my_journals | life.py:280 |
| edu_life | `/my/journals/save` | http | user | 有 | — | my_journals_save | life.py:348 |
| edu_life | `/journals/review` | http | user | 有 | — | journals_review | life.py:384 |
| edu_life | `/journals/review/<int:entry_id>` | http | user | 有 | 读 | journals_review_detail | life.py:413 |
| edu_life | `/journals/review/<int:entry_id>/grade` | http | user | 有 | 读 | journals_review_grade | life.py:435 |
| edu_life | `/checkins/stats` | http | user | 有 | 读 | checkin_stats | life.py:463 |
| edu_life | `/checkins/stats/export` | http | user | 有 | 读 | checkin_stats_export | life.py:574 |
| edu_portal | `/my/assets` | http | user | 有 | 读 | my_assets | assets.py:18 |
| edu_portal | `/my/assets/apply` | http | user | 有 | 读 | asset_apply | assets.py:46 |
| edu_portal | `/my/avatar/upload` | http | user | 无 | 写 | avatar_upload | avatar.py:17 |
| edu_portal | `/student/attendance` | http | user | 收敛 | — | student_attendance | batch1.py:117 |
| edu_portal | `/student/attendance/export` | http | user | 有 | 读 | student_attendance_export | batch1.py:194 |
| edu_portal | `/student/profile` | http | user | 收敛 | 读 | student_profile | batch1.py:237 |
| edu_portal | `/student/exam` | http | user | 收敛 | 读 | student_exam | batch1.py:441 |
| edu_portal | `/student/exam/data/<int:eid>` | http | user | 有 | 读 | student_exam_data | batch1.py:596 |
| edu_portal | `/student/assignment/details` | http | user | 收敛 | 读 | student_assignment_details | batch1.py:637 |
| edu_portal | `/submited/assignment/list/<int:aid>` | http | user | 有 | — | assignment_submit_page | batch1.py:791 |
| edu_portal | `/submited/assignment/list/<int:aid>/save` | http | user | 有 | — | assignment_submit_save | batch1.py:808 |
| edu_portal | `/my/assignment/sub/<int:sid>/file` | http | user | 收敛 | 读 | assignment_sub_file | batch1.py:829 |
| edu_portal | `/my/skill/save` | http | user | 收敛 | — | my_skill_save | batch1.py:868 |
| edu_portal | `/my/offer/set_state` | http | user | 收敛 | 读 | my_offer_set_state | batch1.py:886 |
| edu_portal | `/my/leave/withdraw` | http | user | 收敛 | 读 | my_leave_withdraw | batch1.py:905 |
| edu_portal | `/my/invoice/pdf/<int:move_id>` | http | user | 收敛 | 读 | my_invoice_pdf | batch1.py:929 |
| edu_portal | `/my/apology/save` | http | user | 收敛 | — | my_apology_save | batch1.py:969 |
| edu_portal | `/grade-book` | http | user | 收敛 | 读 | grade_book | batch2.py:1021 |
| edu_portal | `/grade-book/report/download` | http | user | 有 | 读 | grade_book_download | batch2.py:1083 |
| edu_portal | `/student/progression` | http | user | 收敛 | 读 | student_progression | batch2.py:1121 |
| edu_portal | `/library/media` | http | user | 收敛 | 读 | library_media | batch2.py:1214 |
| edu_portal | `/subject/details` | http | user | 无 | 读 | subject_details | batch2.py:1303 |
| edu_portal | `/library/media/info/<int:mid>` | http | user | 有 | 读 | library_media_info | batch2.py:1384 |
| edu_portal | `/subject/material/detail/<int:sid>` | http | user | 有 | 读 | subject_material_detail | batch2.py:1397 |
| edu_portal | `/my/notice_board/notice` | http | user | 收敛 | 读 | notice_board | batch2.py:1427 |
| edu_portal | `/my/notice/<int:notice_id>` | http | user | 无 | 读 | notice_detail | batch2.py:1516 |
| edu_portal | `/my/notice_banner` | http | user | 无 | 读 | notice_banner | batch2.py:1542 |
| edu_portal | `/my/notice_board/all_read` | http | user | 无 | 读 | notice_all_read | batch2.py:1570 |
| edu_portal | `/my/home` | http | user | 无 | — | edu_home | batch2.py:1896 |
| edu_portal | `/my/apps` | http | user | 无 | — | edu_apps | batch2.py:1946 |
| edu_portal | `/alerts/mark_read` | http | user | 无 | — | alerts_mark_read | batch2.py:1990 |
| edu_portal | `/certificate` | http | user | 收敛 | 读 | certificate | batch3.py:83 |
| edu_portal | `/my/certificate/download/<int:cert_id>` | http | user | 有 | 读 | certificate_download | batch3.py:123 |
| edu_portal | `/my-library` | http | user | 收敛 | 读 | my_library | batch3.py:146 |
| edu_portal | `/course/change/request` | http | user | 收敛 | 读 | course_change_request | batch3.py:215 |
| edu_portal | `/course/change/request/save` | http | user | 有 | 读写 | course_change_request_save | batch3.py:260 |
| edu_portal | `/my/time_off/save` | http | user | 有 | 读写 | my_time_off_save | batch3.py:293 |
| edu_portal | `/my/grievances/save` | http | user | 有 | 读写 | my_grievances_save | batch3.py:323 |
| edu_portal | `/subject/registration` | http | user | 收敛 | 读 | subject_registration | batch3.py:354 |
| edu_portal | `/subject/registration/data/<int:rid>` | http | user | 有 | 读 | subject_registration_data | batch3.py:459 |
| edu_portal | `/requested/queue/list` | http | user | 收敛 | 读 | requested_queue_list | batch3.py:482 |
| edu_portal | `/my/time_off` | http | user | 收敛 | 读 | my_time_off | batch3.py:548 |
| edu_portal | `/my/time_off/export` | http | user | 有 | 读 | my_time_off_export | batch3.py:620 |
| edu_portal | `/meeting/information` | http | user | 无 | — | meeting_information | batch3.py:658 |
| edu_portal | `/online/meeting` | http | user | 无 | — | online_meeting | batch3.py:680 |
| edu_portal | `/users/result-overview` | http | user | 收敛 | 读 | users_result_overview | batch3.py:733 |
| edu_portal | `/my/grievances` | http | user | 收敛 | 读 | my_grievances | batch3.py:781 |
| edu_portal | `/my/grievances/export` | http | user | 有 | 读 | my_grievances_export | batch3.py:854 |
| edu_portal | `/my/academic-calendar` | http | user | 无 | 读 | my_academic_calendar | batch3.py:886 |
| edu_portal | `/my/dms` | http | user | 无 | — | my_dms | batch3.py:971 |
| edu_portal | `/my/asset-request` | http | user | 无 | — | my_asset_request | batch3.py:975 |
| edu_portal | `/my/thesis` | http | user | 无 | — | my_thesis | batch3.py:980 |
| edu_portal | `/my/calendar` | http | user | 无 | — | my_calendar | calendar.py:344 |
| edu_portal | `/my/calendar/new` | http | user | 有 | — | calendar_new | calendar.py:763 |
| edu_portal | `/my/calendar/create` | http | user | 有 | — | calendar_create | calendar.py:826 |
| edu_portal | `/my/contacts` | http | user | 收敛 | — | my_contacts | contacts.py:48 |
| edu_portal | `/edu/backend/relink_identity` | http | user | 有 | — | relink_form | contacts.py:224 |
| edu_portal | `/edu/backend/relink_identity/save` | http | user | 有 | — | relink_save | contacts.py:300 |
| edu_portal | `/downloads` | http | user | 无 | — | downloads_index | downloads.py:330 |
| edu_portal | `/downloads/file/<int:fid>` | http | user | 有 | 读 | downloads_file | downloads.py:513 |
| edu_portal | `/downloads/need-ack/<int:fid>` | http | user | 有 | 读 | downloads_need_ack | downloads.py:555 |
| edu_portal | `/downloads/ack/<int:fid>/save` | http | user | 无 | 读 | downloads_ack_save | downloads.py:569 |
| edu_portal | `/downloads/unacked/<int:fid>` | http | user | 有 | 读 | downloads_unacked | downloads.py:581 |
| edu_portal | `/downloads/unacked/<int:fid>/export` | http | user | 有 | 读 | downloads_unacked_export | downloads.py:603 |
| edu_portal | `/downloads/remind/<int:fid>/save` | http | user | 有 | 读 | downloads_remind | downloads.py:618 |
| edu_portal | `/downloads/mine` | http | user | 收敛 | — | downloads_mine | downloads.py:639 |
| edu_portal | `/downloads/mine/export` | http | user | 收敛 | 读 | downloads_mine_export | downloads.py:656 |
| edu_portal | `/downloads/manage` | http | user | 有 | — | downloads_manage | downloads.py:718 |
| edu_portal | `/downloads/folder/save` | http | user | 有 | — | downloads_folder_save | downloads.py:735 |
| edu_portal | `/downloads/folder/delete` | http | user | 有 | 读 | downloads_folder_delete | downloads.py:767 |
| edu_portal | `/downloads/upload` | http | user | 有 | — | downloads_upload | downloads.py:796 |
| edu_portal | `/downloads/upload/save` | http | user | 有 | — | downloads_upload_save | downloads.py:804 |
| edu_portal | `/downloads/manage/bulk` | http | user | 有 | — | downloads_manage_bulk | downloads.py:867 |
| edu_portal | `/downloads/manage/file/update` | http | user | 有 | — | downloads_manage_file_update | downloads.py:923 |
| edu_portal | `/downloads/stats` | http | user | 有 | — | downloads_stats | downloads.py:964 |
| edu_portal | `/downloads/stats/export` | http | user | 有 | — | downloads_stats_export | downloads.py:1010 |
| edu_portal | `/subject/enroll` | http | user | 有 | 读 | enroll_catalog | enroll.py:57 |
| edu_portal | `/subject/enroll/save` | http | user | 有 | 读写 | enroll_save | enroll.py:197 |
| edu_portal | `/student/subjects` | http | user | 有 | 读 | my_subjects | enroll.py:297 |
| edu_portal | `/registrar/subject/approvals` | http | user | 有 | — | approvals | enroll.py:326 |
| edu_portal | `/registrar/subject/approvals/<int:rid>` | http | user | 有 | 读 | approval_detail | enroll.py:385 |
| edu_portal | `/registrar/subject/approvals/<int:rid>/set_state` | http | user | 有 | 读 | set_state | enroll.py:436 |
| edu_portal | `/registrar/subject/set_state_bulk` | http | user | 有 | — | set_state_bulk | enroll.py:463 |
| edu_portal | `/my/evaluation` | http | user | 收敛 | 读 | eval_center | evaluation.py:32 |
| edu_portal | `/my/evaluation/new` | http | user | 有 | 读 | eval_new | evaluation.py:63 |
| edu_portal | `/my/evaluation/create` | http | user | 有 | 读写 | eval_create | evaluation.py:77 |
| edu_portal | `/my/evaluation/task/<int:task_id>` | http | user | 有 | 读 | eval_task | evaluation.py:109 |
| edu_portal | `/my/evaluation/task/<int:task_id>/save` | http | user | 有 | 读 | eval_task_save | evaluation.py:131 |
| edu_portal | `/my/evaluation/results` | http | user | 有 | 读 | eval_results | evaluation.py:156 |
| edu_portal | `/my/evaluation/results.csv` | http | user | 有 | 读 | eval_results_csv | evaluation.py:201 |
| edu_portal | `/my/favorites/save` | http | user | 收敛 | — | favorites_save | favorite.py:24 |
| edu_portal | `/my/notify` | http | user | 收敛 | — | notify_prefs | favorite.py:54 |
| edu_portal | `/my/notify/save` | http | user | 收敛 | — | notify_prefs_save | favorite.py:70 |
| edu_portal | `/my/fees` | http | user | 收敛 | — | my_fees | fees.py:61 |
| edu_portal | `/my/fees/export` | http | user | 收敛 | — | my_fees_export | fees.py:138 |
| edu_portal | `/my/reimburse/receipt/<int:bill_id>/<int:att_id>` | http | user | 有 | 读 | reimburse_receipt | fees.py:195 |
| edu_portal | `/my/reimburse/apply` | http | user | 有 | — | reimburse_apply | fees.py:232 |
| edu_portal | `/my/reimburse/apply/save` | http | user | 有 | 写 | reimburse_apply_save | fees.py:257 |
| edu_portal | `/help` | http | public | 无 | — | help_index | help_center.py:35 |
| edu_portal | `/help/student` | http | public | 无 | — | help_student | help_center.py:40 |
| edu_portal | `/help/faculty` | http | public | 无 | — | help_faculty | help_center.py:45 |
| edu_portal | `/help/parent` | http | public | 无 | — | help_parent | help_center.py:50 |
| edu_portal | `/help/registrar` | http | public | 无 | — | help_registrar | help_center.py:55 |
| edu_portal | `/my/calendar/ics/<token>` | http | public | 有 | 读 | ical_feed | ical.py:96 |
| edu_portal | `/ledger` | http | user | 有 | — | ledger | ledger.py:133 |
| edu_portal | `/ledger/export` | http | user | 有 | — | ledger_export | ledger.py:231 |
| edu_portal | `/ledger/new` | http | user | 有 | — | ledger_new | ledger.py:322 |
| edu_portal | `/ledger/new/save` | http | user | 有 | 读 | ledger_new_save | ledger.py:335 |
| edu_portal | `/ledger/reimburse` | http | user | 有 | — | ledger_reimburse | ledger.py:448 |
| edu_portal | `/ledger/reimburse/set` | http | user | 有 | 读 | ledger_reimburse_set | ledger.py:505 |
| edu_portal | `/my/courses` | http | user | 收敛 | 读 | my_courses | lms.py:46 |
| edu_portal | `/my/courses/<int:subject_id>` | http | user | 有 | 读 | course_lessons | lms.py:99 |
| edu_portal | `/my/courses/lesson/<int:lesson_id>` | http | user | 收敛 | 读 | lesson_detail | lms.py:146 |
| edu_portal | `/my/courses/lesson/<int:lesson_id>/done` | http | user | 有 | 读 | lesson_done | lms.py:189 |
| edu_portal | `/my/home` | http | user | 无 | — | edu_home | main.py:108 |
| edu_portal | `/my` | http | user | 无 | — | edu_my_redirect | main.py:119 |
| edu_portal | `/login` | http | public | 无 | — | edu_login | main.py:150 |
| edu_portal | `/reset_password` | http | none | 无 | — | edu_reset_password | main.py:165 |
| edu_portal | `/logout` | http | user | 无 | — | edu_logout | main.py:198 |
| edu_portal | `/apps` | http | public | 有 | — | apps_menu | main.py:212 |
| edu_portal | `/openeducat/apps_menu` | http | public | 无 | — | apps_menu_legacy | main.py:221 |
| edu_portal | `/register` | http | public | 无 | — | register_form | main.py:243 |
| edu_portal | `/register/submit` | http | public | 无 | — | register_submit | main.py:248 |
| edu_portal | `/web/register` | http | public | 无 | — | register_form_legacy | main.py:253 |
| edu_portal | `/web/register/submit` | http | public | 无 | — | register_submit_legacy | main.py:258 |
| edu_portal | `/my/messages` | http | user | 收敛 | — | messages_list | messages.py:246 |
| edu_portal | `/my/messages/<int:uid>` | http | user | 有 | — | messages_chat | messages.py:312 |
| edu_portal | `/my/messages/send` | http | user | 有 | 读写 | messages_send | messages.py:356 |
| edu_portal | `/my/messages/poll` | http | user | 收敛 | — | messages_poll | messages.py:387 |
| edu_portal | `/my/password` | http | user | 无 | — | password_form | my_password.py:24 |
| edu_portal | `/my/password/save` | http | user | 无 | — | password_save | my_password.py:29 |
| edu_portal | `/web/register` | http | public | 无 | — | register_form | register.py:43 |
| edu_portal | `/web/register/submit` | http | public | 收敛 | 读 | register_submit | register.py:55 |
| edu_portal | `/my/child` | http | user | 收敛 | — | my_child | roles.py:259 |
| edu_portal | `/my/child/<int:child_id>` | http | user | 有 | 读 | my_child_dashboard | roles.py:272 |
| edu_portal | `/attendance/take` | http | user | 有 | 读 | attendance_take | roles.py:348 |
| edu_portal | `/attendance/save` | http | user | 有 | 读写 | attendance_save | roles.py:447 |
| edu_portal | `/attendance/selfcheck/start` | http | user | 有 | — | attendance_selfcheck_start | roles.py:529 |
| edu_portal | `/attendance/selfcheck/stop` | http | user | 有 | — | attendance_selfcheck_stop | roles.py:558 |
| edu_portal | `/attendance/selfcheck/<token>` | http | user | 有 | 读 | attendance_selfcheck_scan | roles.py:574 |
| edu_portal | `/grading/entry` | http | user | 有 | 读 | grading_entry | roles.py:702 |
| edu_portal | `/grading/save` | http | user | 有 | — | grading_save | roles.py:749 |
| edu_portal | `/assignment/publish` | http | user | 有 | 读 | assignment_publish | roles.py:796 |
| edu_portal | `/assignment/publish_save` | http | user | 有 | 写 | assignment_publish_save | roles.py:813 |
| edu_portal | `/my/child/<int:child_id>/leave , /my/child/<int:child_id>/leave/saved` | http | user | 收敛 | 读 | child_leave_form | roles.py:858 |
| edu_portal | `/my/child/<int:child_id>/leave/save` | http | user | 收敛 | 读 | child_leave_save | roles.py:873 |
| edu_portal | `/leave/approvals` | http | user | 有 | — | leave_approvals | roles.py:898 |
| edu_portal | `/leave/set_state` | http | user | 有 | — | leave_set_state | roles.py:942 |
| edu_portal | `/grievances/approvals` | http | user | 有 | — | grievance_approvals | roles.py:1046 |
| edu_portal | `/grievances/approvals/<int:gid>` | http | user | 有 | — | grievance_detail | roles.py:1094 |
| edu_portal | `/grievances/set_state` | http | user | 有 | — | grievance_set_state | roles.py:1113 |
| edu_portal | `/leave/approvals/<int:leave_id>` | http | user | 有 | — | leave_detail | roles.py:1149 |
| edu_portal | `/notice/publish` | http | user | 有 | 读 | notice_publish | roles.py:1174 |
| edu_portal | `/notice/publish_save` | http | user | 有 | 读写 | notice_publish_save | roles.py:1192 |
| edu_portal | `/alumni/job/list` | http | user | 无 | 读 | alumni_job_list | roles.py:1302 |
| edu_portal | `/openeducat/apps_menu` | http | user | 无 | — | apps_menu | roles.py:1322 |
| edu_portal | `/alerts/mark_read` | http | user | 收敛 | — | alerts_mark_read | roles.py:1385 |
| edu_portal | `/edu/audit` | http | user | 有 | — | edu_audit | roles.py:1407 |
| edu_portal | `/assignment/manage` | http | user | 有 | — | assignment_manage | roles.py:1472 |
| edu_portal | `/assignment/edit/<int:aid>` | http | user | 有 | — | assignment_edit | roles.py:1513 |
| edu_portal | `/assignment/edit/<int:aid>/save` | http | user | 有 | — | assignment_edit_save | roles.py:1532 |
| edu_portal | `/assignment/set_state` | http | user | 无 | — | assignment_set_state | roles.py:1558 |
| edu_portal | `/assignment/submissions/<int:aid>` | http | user | 有 | 读 | assignment_submissions | roles.py:1576 |
| edu_portal | `/edu/import/students` | http | user | 有 | — | edu_import_students | roles.py:1620 |
| edu_portal | `/edu/import/students/preview` | http | user | 有 | — | edu_import_students_preview | roles.py:1633 |
| edu_portal | `/edu/import/students/commit` | http | user | 有 | — | edu_import_students_commit | roles.py:1713 |
| edu_portal | `/leave/set_state_bulk` | http | user | 有 | — | leave_set_state_bulk | roles.py:1829 |
| edu_portal | `/grievances/set_state_bulk` | http | user | 有 | — | grievance_set_state_bulk | roles.py:1880 |
| edu_portal | `/approvals/delegate` | http | user | 有 | 读 | approval_delegate | roles.py:1932 |
| edu_portal | `/approvals/delegate/save` | http | user | 有 | 写 | approval_delegate_save | roles.py:1954 |
| edu_portal | `/approvals/delegate/cancel` | http | user | 有 | 读 | approval_delegate_cancel | roles.py:1990 |
| edu_portal | `/grading/export` | http | user | 有 | 读 | grading_export | roles.py:2014 |
| edu_portal | `/grading/import` | http | user | 有 | 读 | grading_import | roles.py:2046 |
| edu_portal | `/grading/import/commit` | http | user | 有 | — | grading_import_commit | roles.py:2119 |
| edu_portal | `/grading/copy_prev` | http | user | 有 | 读 | grading_copy_prev | roles.py:2162 |
| edu_portal | `/grading/history` | http | user | 有 | 读 | grading_history | roles.py:2217 |
| edu_portal | `/attendance/import` | http | user | 有 | 读 | attendance_import | roles.py:2266 |
| edu_portal | `/attendance/import/commit` | http | user | 有 | 读 | attendance_import_commit | roles.py:2339 |
| edu_portal | `/notice/template/save` | http | user | 有 | 写 | notice_template_save | roles.py:2423 |
| edu_portal | `/my/documents` | http | user | 有 | — | my_documents | roles.py:2451 |
| edu_portal | `/my/documents/enrollment-certificate` | http | user | 有 | — | my_enrollment_certificate | roles.py:2505 |
| edu_portal | `/my/documents/transcript` | http | user | 有 | — | my_transcript | roles.py:2517 |
| edu_portal | `/student/timetable` | http | user | 收敛 | 读 | student_timetable | scheduling.py:79 |
| edu_portal | `/my/search` | http | user | 收敛 | 读 | my_search | search.py:20 |
| edu_portal | `/my/lang/<string:code>` | http | public | 无 | 写 | set_lang | search.py:185 |
| edu_portal | `/my/help` | http | user | 无 | — | help_center | search.py:197 |
| edu_portal | `/my/study` | http | user | 收敛 | — | my_study | study.py:274 |
| edu_portal | `/my/study/<int:subject_id>` | http | user | 有 | 读 | study_subject | study.py:325 |
| edu_portal | `/my/study/session/<int:session_id>/join` | http | user | 有 | 读 | session_join | study.py:353 |
| edu_portal | `/my/study/session/<int:session_id>/link/save` | http | user | 有 | 读 | session_link_save | study.py:379 |
| edu_portal | `/my/checkin` | http | user | 无 | — | my_checkin | welfare.py:65 |
| edu_portal | `/my/checkin/export` | http | user | 无 | — | my_checkin_export | welfare.py:70 |
| edu_portal | `/my/checkin/save` | http | user | 无 | — | my_checkin_save | welfare.py:76 |
| edu_portal | `/my/checkin/board` | http | user | 有 | 读 | checkin_board | welfare.py:95 |
| edu_portal | `/my/points` | http | user | 有 | 读 | my_points_give_page | welfare.py:139 |
| edu_portal | `/my/points/give` | http | user | 有 | 读写 | my_points_give | welfare.py:178 |
| edu_portal | `/my/points/me` | http | user | 有 | 读 | my_points_me | welfare.py:222 |
| edu_public | `/courses` | http | public | 无 | — | public_courses | main.py:43 |
| edu_public | `/online-exams` | http | public | 无 | — | public_exams | main.py:74 |
| edu_public | `/digital-library` | http | public | 无 | — | digital_library | main.py:89 |
| edu_public | `/digital-library/material/<int:mid>` | http | public | 有 | 读 | digital_library_material | main.py:126 |
| edu_public | `/booking` | http | public | 无 | — | booking | main.py:141 |
| edu_public | `/alumni` | http | public | 无 | 读 | alumni | main.py:148 |
| edu_public | `/campus/jobs` | http | public | 无 | 读 | campus_jobs | main.py:154 |
| edu_public | `/campus/jobs/<int:posting_id> , /campus/jobs/<int:posting_id>/sent` | http | public | 有 | 读 | campus_job_detail | main.py:164 |
| edu_public | `/campus/jobs/<int:posting_id>/apply` | http | public | 有 | 读写 | campus_job_apply | main.py:178 |
| edu_public | `/alumni/job/card` | http | public | 无 | 读 | alumni_job_card | main.py:199 |
| edu_public | `/alumni/jobs` | http | public | 无 | — | alumni_jobs_page | main.py:206 |
| edu_public | `/courses-offered` | http | public | 无 | 读 | courses_offered | main.py:240 |
| edu_public | `/program-offered` | http | public | 无 | 读 | program_offered | main.py:246 |
| edu_public | `/my-courses` | http | user | 收敛 | 读 | my_courses | main.py:253 |
| edu_quiz | `/quiz` | http | user | 收敛 | 读 | quiz_list | portal.py:39 |
| edu_quiz | `/quiz/my` | http | user | 有 | 读 | quiz_my | portal.py:74 |
| edu_quiz | `/quiz/<int:qid>/take` | http | user | 有 | 读 | quiz_take | portal.py:100 |
| edu_quiz | `/quiz/<int:qid>/submit` | http | user | 有 | 读写 | quiz_submit | portal.py:117 |
| edu_quiz | `/quiz/<int:qid>/result/<int:aid>` | http | user | 收敛 | 读 | quiz_result | portal.py:160 |
| edu_schedule | `/timetable/bulk` | http | user | 有 | — | timetable_bulk | main.py:425 |
| edu_schedule | `/timetable/bulk/preview` | http | user | 有 | — | timetable_bulk_preview | main.py:436 |
| edu_schedule | `/timetable/bulk/create` | http | user | 有 | 读 | timetable_bulk_create | main.py:459 |
| edu_schedule | `/timetable/session/<int:sid>/impact` | http | user | 有 | 读 | session_impact | main.py:505 |
| edu_schedule | `/timetable/session/<int:sid>/notify` | http | user | 有 | 读 | session_notify | main.py:535 |
| edu_telegram | `/telegram/webhook` | http | public | 无 | — | telegram_webhook | main.py:992 |
| edu_telegram | `/telegram/report/<string:token>` | http | public | 有 | — | telegram_report | main.py:1026 |
| edu_telegram | `/my/telegram` | http | user | 无 | — | telegram_binding | portal.py:26 |
| edu_telegram | `/my/telegram/new_code` | http | user | 无 | — | telegram_new_code | portal.py:33 |
| edu_telegram | `/my/subject-reg` | http | user | 无 | 读 | subject_reg | portal_ops.py:30 |
| edu_telegram | `/my/subject-reg/save` | http | user | 无 | 读 | subject_reg_save | portal_ops.py:56 |
| edu_telegram | `/my/rollcall` | http | user | 无 | 读 | rollcall_index | portal_ops.py:76 |
| edu_telegram | `/my/rollcall/<int:session_id>` | http | user | 无 | 读 | rollcall_form | portal_ops.py:93 |
| edu_telegram | `/my/rollcall/<int:session_id>/save` | http | user | 有 | 读 | rollcall_save | portal_ops.py:134 |
| edu_telegram | `/my/marks` | http | user | 无 | 读 | marks_index | portal_ops.py:185 |
| edu_telegram | `/my/marks/<int:exam_id>` | http | user | 无 | 读 | marks_form | portal_ops.py:199 |
| edu_telegram | `/my/marks/<int:exam_id>/save` | http | user | 无 | 读 | marks_save | portal_ops.py:213 |
| edu_tg_bind | `/telegram/tgb/webhook` (WEBHOOK_PATH 常量) | http | public | 无 | — | telegram_tgb_webhook | webhook.py:42 |
---

## 3. 越权实测（IDOR）逐条结果

会话说明：**anu**=匿名，**stu**=stu@local（门户/学生），**parent**=parent@local（门户/家长），**fac**=faculty@local（内部/教师）。
全部为 GET、不跟随跳转；返回值 = HTTP 状态码（跳转时附 Location）。命中判据 = 200 **且响应正文含非本人数据**。

### 3.1 命中（IDOR 成立）

| # | 路径 | anu | stu | parent | fac | 结论 |
|---|---|---|---|---|---|---|
| 1 | `/subject/registration/data/10` | 303→login | 200（本人） | **200 拿到数据** | **200 拿到数据** | **越权命中**：非学生身份不做归属校验 |
| 2 | `/subject/registration/data/72` | 303→login | 303 | **200 拿到数据** | **200 拿到数据** | **越权命中**（student_id 为空也被放行） |
| 3 | RPC `call_kw/edu.notify.pref/search_read` | 303→login | 200（6 行） | **200（6 行，全属 uid=8）** | — | **跨用户读命中** |
| 4 | RPC `call_kw/edu.leave / edu.grievance / edu.daily.checkin` | 303→login | 200 | **200（12 / 22 / 7 行，全量）** | — | **无行过滤命中** |

命中 1 的证据（parent 会话实际渲染内容）：

`@
SR0008 · 注册详情
学生  王小明          <- 被渲染的学生姓名
课程  基督教研究硕士科
班级  预备科 · 2026级【演示】
状态  已提交
`@

同一 parent 会话访问 `/subject/registration`（列表页）却只显示空列表——**列表页按 student.id 收敛，详情页不收敛**，
说明这不是「设计如此」，而是详情页漏了归属判断：

`@python
# custom_addons/edu_portal/controllers/batch3.py:459
student = current_student()
r = env['op.subject.registration'].sudo().browse(rid)
if not r.exists() or (student and r.student_id.id != student.id):   # student 为 None 时整个条件短路为 False
    return request.redirect('/subject/registration')
`@

结论：任何**没有 op.student 档案**的已登录账号（家长、教师、教务、以及学生档案未挂接的账号）都能枚举 rid 读任意注册单。

### 3.2 未命中（门禁生效，逐条留证）

| 路径 | anu | stu | parent | fac |
|---|---|---|---|---|
| `/registrar/subject/approvals` | 303→login | **303→/my/home** | 303→/my/home | 200（教师，设计内） |
| `/registrar/subject/approvals/536` | 303→login | **303→/my/home** | 303→/my/home | 200 |
| `/registrar/subject/set_state_bulk`（POST） | 405 | **405** | 405 | 405 |
| `/leave/approvals`、`/leave/approvals/14` | 303→login | **303→/my/home** | 303→/my/home | 200 |
| `/grievances/approvals`、`/grievances/approvals/1` | 303→login | **303→/my/home** | 303→/my/home | 200 |
| `/edu/audit`、`/edu/import/students*`、`/edu/backend/relink_identity` | 303→login | **303→/my/home** | 303→/my/home | 303 / 200 |
| `/ledger`、`/ledger/new`、`/ledger/reimburse` | 303→login | **303→/my/home** | 303→/my/home | 200 |
| `/attendance/take`、`/grading/entry`、`/grading/export`、`/assignment/manage` | 303→login | **303→/my/home** | 303→/my/home | 200 |
| `/downloads/manage`、`/downloads/stats`、`/downloads/stats/export` | 303→login | **303→/downloads** | 303→/downloads | 303→/downloads |
| `/downloads/unacked/1233/export` | 303→login | **404** | 404 | 404 |
| `/timetable/bulk`、`/timetable/session/1/impact` | 303→login | **303→/my/home** | 303→/my/home | 200 |
| `/my/child/7` `/8` `/9`（他人孩子） | 303→login | **303→/my/child** | **303→/my/child** | 303→/my/child |
| `/my/child/7/leave`（为他人孩子请假） | 303→login | 303→/my/child | **303→/my/child** | 303→/my/child |
| `/my/child/5`（本人孩子） | 303→login | 303→/my/child | 200（正确） | 303→/my/child |
| `/quiz/1/result/1`（他人 attempt） | 303→login | 200（本人） | **303→/quiz** | 303→/quiz |
| `/quiz/1/result/999`（不存在） | 303→login | 303→/quiz | 303→/quiz | 303→/quiz |
| `/student/exam/data/1`、`/library/media/info/1`、`/subject/material/detail/1` | 303→login | 303 | 303 | 303 |
| `/assignment/edit/1`、`/assignment/submissions/1` | 303→login | 303 | 303 | 303 |
| `/my/certificate/download/1` `/2`（不存在） | 303→login | 404 | 404 | 404 |
| `/my/invoice/pdf/1`（非本人/不存在） | 303→login | 303→/student/profile | 303→/student/profile | 303→/student/profile |
| `/my/reimburse/receipt/1/1` | 303→login | 404 | 404 | 404 |
| `/downloads/file/1233` `/1` `/1024` | 303→login | 404 | 404 | 404 |
| `/my/courses/35` `/54` `/my/courses/lesson/1` | 303→login | 303→/my/courses | 303→/my/courses | 200 |
| `/my/study/35`、`/my/study/session/1/join` | 303→login | 303→/my/study | 303→/my/study | 303 / 200 |
| `/my/messages/1`（__system__ 技术账号） | 303→login | 303→/my/messages | 303→/my/messages | 303→/my/messages |
| `/my/messages/10`（家长） | 303→login | 303→/my/messages | 303→/my/messages | 200（同圈） |
| `/my/messages/2` `/11` `/12` | 303→login | 200 | 200 | 200 |
| `/web`、`/odoo/settings` | 303→login | **303→/my** | 303→/my | 200（内部，设计内） |

**`/my/messages/<uid>` 说明**（看似命中，实为设计内）：对话线程按 `thread_key = min-max` 严格隔离，
学生只能读到「我 ↔ 对方」的消息；admin/教师出现在可选对象里是「学生可给管理员发私信」的产品设定，
**没有跨会话读取他人的消息**。`/my/messages/1`（__system__ 技术账号）与 `/my/messages/10`（家长，对学生不在圈内）都被正确拒绝。

### 3.3 RPC 直读实测（绕开控制器门禁，直接打模型 ACL / ir.rule）

这是本次最关键的一组实验：门户控制器再严，也拦不住 `POST /web/dataset/call_kw/<model>/<method>` 这一类
Odoo 原生 JSON 路由——它只受**模型层 ACL + ir.rule** 约束。

| 模型 | 是否有 ir.rule | stu@local (uid 8) | parent@local (uid 10) | 判定 |
|---|---|---|---|---|
| edu.notify.pref | **无**（且门户可写） | 6 行 | **6 行**（6 行全属 uid=8） | **跨用户读** |
| edu.daily.checkin | **无** | 7 行 | **7 行**（全属 student 5） | 全量返回 |
| edu.leave | **无** | 12 行 | **12 行** | 全量返回 |
| edu.grievance | **无** | 22 行 | **22 行** | 全量返回 |
| edu.point.log | **无** | 2 行 | 2 行 | 全量返回 |
| edu.placement.offer | **无** | 1 行 | 1 行 | 全量返回 |
| edu.student.skill | **无** | 1 行 | 1 行 | 全量返回 |
| edu.quiz | **无** | 1 行 | 1 行 | 全量返回 |
| edu.journal.entry | 有（仅本人） | 4 行 | **0 行** | 行过滤生效 |
| edu.certificate | 有（仅本人） | 1 行 | **0 行** | 行过滤生效 |
| edu.checkin.record | 有（仅本人） | 53 行 | **0 行** | 行过滤生效 |
| edu.message | 有（仅收发双方） | 拒绝访问 | 拒绝访问 | 行过滤生效 |
| edu.eval.task | 无门户 ACL | 拒绝访问 | 拒绝访问 | ACL 拦截 |
| op.student | 有（仅本人/孩子） | 0 行 | 0 行 | 行过滤生效 |
| res.partner | 有（门户仅本人） | 1 行（自己） | 1 行（自己） | 行过滤生效 |

**对照实验的意义**：同一个 parent 账号，对**有 ir.rule** 的模型读到 0 行（被行过滤挡掉），
对**没有 ir.rule** 的模型读到与数据所有者完全相同的行数，证明这些表**根本没有行级过滤**，是全表可取。
`edu.notify.pref` 更能证明是「跨用户」：6 行的 user_id 全部是 8（学生），而 parent 的 uid 是 10。

门户账号之所以能发这些 RPC，是因为 `ir.model.access` 给了 `base.group_portal` 读权限（见第 5 节）。


---

## 4. 发现清单（证据 → 影响面 → 风险等级 → 修复建议）

### F1 —— 【严重】edu 模型缺 ir.rule：任意门户账号一条 RPC 读走全校数据

**证据**
1. `custom_addons/edu_portal/security/` 目录下**只有 ir.model.access.csv，没有 security.xml**，即该模块从未定义过任何 ir.rule。
   对照组：`edu_life/security/` 与 `edu_eval/security/` 都是 CSV + security.xml 成对存在，所以 edu.checkin.record / edu.journal.entry / edu.admin.eval.score 才有行规则。
2. 数据库实测：`ir_rule` 表里 edu 开头的模型**只有 7 个模型共 10 条规则**（edu.certificate / edu.checkin.record / edu.journal.entry / edu.message / edu.admin.eval.score / edu.fee.bill / edu.invite.code）。
3. `custom_addons/edu_portal/security/ir.model.access.csv:4`
   `access_edu_leave_portal,edu.leave portal,model_edu_leave,base.group_portal,1,0,0,0`
   —— 门户对 edu.leave 有**整表读权限**，却没有任何规则限制行。
4. 生产库逐条比对：**ACL 与 ir.rule 与本地完全一致**（生产同样只有 10 条 edu 规则，同样缺 edu.leave / edu.grievance 等）。

**受影响模型清单**（门户有读权限但无任何 ir.rule）

| 模型 | 门户 ACL | ir.rule |
|---|---|---|
| edu.leave（请假） | 读 | **无** |
| edu.grievance（申诉） | 读 | **无** |
| edu.daily.checkin | 读 | **无** |
| edu.placement.offer | 读 | **无** |
| edu.point.log | 读 | **无** |
| edu.student.skill | 读 | **无** |
| edu.quiz | 读 | **无** |
| edu.checkin.type / edu.fee.category | 读 | **无** |
| edu.admin.eval.item / edu.admin.eval.template | 读 | **无** |
| **edu.favorite / edu.notify.pref** | **读+写+建+删** | **无** |

**影响面**
- 生产有 **21 个门户账号**（全部是学生，login 就是学生本人邮箱），全部可发
  `POST /web/dataset/call_kw/edu.leave/search_read`，一次请求拿到**全部学生的请假记录**
  （姓名、请假类型、事由、审批状态）。edu.grievance 同理（学生申诉）。
- 更糟的是 `edu.favorite` / `edu.notify.pref` 门户是 **1,1,1,1**，即越权**改/删**他人记录（本次未实测，见未验证项）。
- 严重程度随学生数线性放大。本地只有 1 名学生有业务数据，所以本地「看起来」只有 12 行；
  生产 19 名学生、真实姓名与邮箱已确认存在。

**风险等级**：**严重（Critical）** —— 已实测跨用户读成立，且是「一个 HTTP 请求读全表」的量级。

**修复建议**（优先级最高）
1. 在 `custom_addons/edu_portal/security/` 下新增 `security.xml`，为每个门户有读权限的模型补 ir.rule（照抄已有先例的写法）：
   - edu.leave / edu.grievance / edu.placement.offer / edu.point.log / edu.student.skill / edu.daily.checkin：
     `[('student_id.user_id', '=', user.id)]`，家长另加 `('student_id.parent_id.user_ids', 'in', [user.id])`。
   - edu.favorite / edu.notify.pref：`[('user_id', '=', user.id)]`，**并同时下调 ACL 的写权限**。
   - edu.admin.eval.item / template：只放可见字段，或直接把门户读权限收掉（门户经控制器 sudo 读，不需要模型 ACL）。
2. **更彻底的做法（建议一并做）**：把门户专用模型的 ACL 收成 `1,0,0,0`（只读）甚至 `0,0,0,0`，
   门户一律经控制器 `sudo()` 取数——这正是本仓「所有读走 sudo()」的既有约定，ACL 只留后台角色。
   只要 ACL 是 0，RPC 直读这条路整条断掉，不必逐个模型写规则。
3. 加一条**断言脚本**（放 `tests/`）：遍历 `ir.model.access.csv`，凡 `base.group_portal` 的 read=1，
   对应模型必须有 ir.rule 或 ACL 为 0，否则 CI 失败。防止再漏。

---

### F2 —— 【高】`/subject/registration/data/<rid>` 门禁短路，任意非学生账号可枚举读他人选课/换课单

**证据**：见 3.1。源码 `custom_addons/edu_portal/controllers/batch3.py:459`。
parent 与 faculty 会话均 **200** 并渲染出「学生 王小明 / 课程 / 班级 / 状态 / 已注册科目」，
而同一账号的 `/subject/registration` 列表页为空。

**影响面**：全部选课注册单与换课单（`op.subject.registration`）。泄露学生姓名、课程、班级、状态、
申请备注、驳回原因、已注册科目清单。任何**非学生**登录账号（家长最典型：家长本来只该看自己孩子）可遍历 rid 读全库。

**风险等级**：**高**。

**修复建议**：把条件改成显式拒绝，不要依赖短路：

`@python
student = current_student()
if not student:                       # 无学生档案 -> 直接拒
    return request.redirect('/subject/registration')
r = env['op.subject.registration'].sudo().browse(rid)
if not r.exists() or r.student_id.id != student.id:
    return request.redirect('/subject/registration')
`@

若要给家长开放「看自己孩子的单」，需单独加入 `r.student_id.id in parent.student_ids.ids` 分支（现在是完全没有）。
同类写法建议全库扫一遍：`if ... or (student and X != student.id)` 这类**用「身份存在」当前置条件**的授权判断，
都是同一类 bug。

---

### F3 —— 【高】`/alumni` 匿名页渲染真实学生姓名与人员 id（生产已复现）

**证据**
- `custom_addons/edu_public/controllers/main.py:149`：`students = request.env['op.student'].sudo().search([], limit=12)`
  —— **零过滤**，而路由是 `auth='public'`。
- 本地匿名 GET `/alumni` 返回 200，页面含 张同学【演示】/ 李同学【演示】/ 陈同学【演示】/ 王小明 + 头像 URL。
- **生产匿名 GET https://edu.example.org/alumni → 200**，页面里逐个命中 12 个真实学生姓名：
  王佐、花木、余晖、艾志恒、泫、赵军、王院宇、李直、陈雨声、汤沅沅、李宣雨、罗中政，
  并渲染 `/web/image/res.partner/<id>/image_256`（partner id 64 / 81–90 / 92 全部暴露）。
- 补充实测：匿名取头像字节时 Odoo 返回 **6078 字节的固定占位图**，所以**照片本身没有泄露**，
  泄露的是**姓名 + 人员 id**（不要把这条写成「照片泄露」）。

**影响面**：公开可爬取的学生名册（当前 12 人，扩容后随 limit 增加）。页面叫「校友」，
实际列的是**在读学生**（op.student 全部记录），与设计意图不符。

**风险等级**：**高**（匿名可达的真实 PII，已在生产证实）。

**修复建议**
1. 增加真实过滤条件（`state = 'alumni'` / 毕业年 / 本人勾选公开），**不要**用 `search([], limit=12)`。
2. 展示降级：只给「姓名首字 + 学位」，不输出 partner id 与头像 URL。
3. 若确需展示在校生风采，加显式同意开关（res.partner 上的「允许公开」），默认关闭。
4. 顺带复核其余公开页数据源：`/online-exams`（匿名列全部 op.exam 名称与时间）、`/courses` 与 `/courses-offered`（全部课程/科目）、
   `/digital-library` 与 `/digital-library/material/<id>`（`auth='public'` + 任意 op.media）。这批属「内部目录对外」，请业务确认是否可公开。

---

### F4 —— 【高】登录端点**没有任何速率限制**，`base.login_cooldown_*` 是死配置

**证据**
1. Odoo 19 源码里 `res.users._login_cooldown` 有完整实现，但对 `/usr/lib/python3/dist-packages/odoo/` 全量 grep，
   **没有任何调用点**——只有 def、docstring 与自身方法名出现，调用处 0 处，即这个上下文管理器从未挂到登录路径上。
2. 实测（本地）：同一 IP 连续 **13 次**错误密码，每次耗时 **0.02–0.10 秒**，无延迟、无拒绝、无锁定，13 次总耗时 1.1 秒。
3. 生产把参数配好了却因此不生效：`base.login_cooldown_after=10`、`base.login_cooldown_duration=60` 在两库都存在。
4. 生产 `proxy_mode = True`、`workers = 4` —— 即使将来挂上限速，其计数是**每 worker 内存态且按来源 IP**，
   4 个 worker 意味着实际阈值是 10x4；生产 `proxy_mode=True` 是对的（能识别真实客户端 IP），这一点没问题。

**影响面**：`/web/login` 可被无限速在线爆破。与 F3（公开页给出学生姓名）、
`/alumni` 与注册面（生产 21 个门户 login 就是学生邮箱）叠加后风险显著。

**风险等级**：**高**（这是「偷数据」最直接的入口）。

**修复建议**
1. 边缘先加一层：Cloudflare Rate Limiting 或 nginx `limit_req` 对 `/web/login`、`/register`、
   `/web/register/submit` 限速。**这是最快生效的一招**。
2. 应用层：在自定义模块里重写 `res.users._check_credentials` 或挂 `ir.http` 前置钩子实现真正的失败计数
   （按 login + IP，落库跨 worker 生效），不要依赖上游死代码。
3. 运维手册里把 `base.login_cooldown_after` 标注为**无效配置**，避免误以为已有防护。

---

### F5 —— 【中】edu_apply 遗留调试日志把申请人 PII 写进服务端日志

**证据**：`custom_addons/edu_apply/controllers/main.py:60`

`@python
logging.getLogger(__name__).warning("_DBG_COLLECT %s", json.dumps(values, ensure_ascii=False)[:400])
`@

每次公开报名表提交（`/apply/submit`，`auth='public'`）都会把采集到的字段（姓名、电话、教会、性别等）
以 WARNING 级别写进 Odoo 日志，日志随 `log_level = info` 落盘并可能被日志采集/轮转外带。

**影响面**：招生申请 PII（未入学申请人）长期留存在日志里，与最小化留存原则冲突；日志外泄即个人信息泄露。
这段代码没有任何开关，生产同样会写（edu_apply 已装在生产）。

**风险等级**：**中**。

**修复建议**：直接删除该行（`_DBG_` 前缀已表明是临时调试）；如需排障，改为 `_logger.debug` 且
**只记字段名与长度，不记值**。另建议对仓内 `logging....warning` 做一次全量排查。


---

### F6 —— 【中】注册/邀请码面：无限速、人机校验空转、错误文案构成「码是否存在」预言机

**证据**
- `custom_addons/edu_portal/controllers/register.py`：`/web/register/submit` 是 `auth='public'` + `csrf=True`，
  **没有任何速率限制或验证码调用**；码在 `edu.invite.code` 里按字符串精确匹配（`search([('code','=',vals['code'])])`）。
- 实测（本地，仅提交**不存在**的码，未创建任何数据）：
  `EDU-ZZZZZZ` / `EDU-XXXXXX` / `AAAAAAAA` 三次都返回
  `303 -> /register?error=邀请码无效`，响应一致且即时（无冷却迹象）。
- 码格式：`EDU-` 加 6 位（约 32 进制），空间约 1e9，单纯穷举成本较高；但**没有失败次数锁定**，
  且 `_validate_view()` 对「已过期 / 已用完 / 层级不符」返回**不同的错误文案**，
  攻击者可据此区分「码存在但不可用」与「码不存在」，把搜索空间从 1e9 收敛到「已发放的码」。
- `enable_recaptcha = True`、`recaptcha_min_score = 0.7` 在**生产与本地都配了**，
  但两库的 `ir.config_parameter` 里**都没有 recaptcha_public_key / recaptcha_private_key**，该开关**空转**；
  且 `register_submit` 代码里根本没有 recaptcha 校验调用。
- 生产 `auth_signup.invitation_scope = b2b`（原生自助注册已关，必须持码），这一层是对的。

**影响面**：拿到一张有效邀请码即等于拿到一个门户 / 教师 / 教务层级账号（码带 `tier` 与 `identity`，
层级码会把账号直接落进该层级的组）；结合 F4（登录无限速），招生季被刷号的风险实在。

**风险等级**：**中**。

**修复建议**
1. 给 `/web/register/submit` 与 `/apply/submit` 加服务端失败计数（同 IP + 同码前缀），连续 N 次失败即冷却。
2. 同一条路由实装 reCAPTCHA（补 key 并真的调用），或改用「邮箱验证码 / 人工审核」流程。
3. 把 `_validate_view` 的各类失败统一成同一句用户可见文案（只在服务端日志区分），消除预言机。
4. 邀请码缩短有效期、保持单码单用（现为 `use_limit=1`），后台加「最近被尝试的无效码」告警。

---

### F7 —— 【中】证书下载用 `_is_internal()` 放行：任一内部账号可下载任意学生证书 PDF

**证据**：`custom_addons/edu_portal/controllers/batch3.py:123`

`@python
if not cert or not (is_owner or request.env.user._is_internal()):
    return request.not_found()
`@

实测 `/my/certificate/download/3`：学生 200（本人）、家长 **404**、教师（internal）**200 拿到 PDF**。
`_is_internal()` 等价于「share=False」，凡后端账号一律命中，**不区分是否与该学生相关**。

**影响面**：证书是学历证明类文件，含姓名 / 课程 / 编号。任何内部账号（含将来新增的助教、临时工账号）可下载全库证书。

**风险等级**：**中**。

**修复建议**：把 `_is_internal()` 换成显式角色判定（教务/管理员，即 `privileged_staff()`）或
「教师且该生在本班」；越权统一返回 `not_found()` 不泄露存在性。建议全仓搜索 `_is_internal()` 复核同类用法。

---

### F8 —— 【中】ACL 过宽：`base.group_user` 对多张学生业务表是 1,1,1,1

**证据**（`custom_addons/edu_portal/security/ir.model.access.csv`，生产库实测一致）

| 模型 | base.group_user（任意内部员工） |
|---|---|
| edu.leave | 1,1,1,1 |
| edu.grievance | 1,1,1,1 |
| edu.certificate | 1,1,1,1 |
| edu.checkin.record | 1,1,1,1 |
| edu.journal.entry | 1,1,1,1 |
| edu.quiz / edu.quiz.question | 1,1,1,1 |
| edu.asset / edu.asset.loan | 1,1,1,1 |
| edu.student.skill | 1,1,1,1 |
| edu.favorite / edu.notify.pref | 1,1,1,1（门户也是 1,1,1,1） |

即**任何内部账号**都能增删改学生请假、申诉、证书、打卡、周记、测验、资产记录，不区分是否其负责的班级。
门禁只在控制器上，**后端与 RPC 路径没有任何校验**。

**影响面**：内部越权与误操作（删他人数据）风险；申诉 / 请假属敏感个人事项。

**风险等级**：**中**。

**修复建议**：按最小权限重写该 CSV：教务 / 管理员给写权限，`base.group_user` 降为只读或 0；
控制器本来就走 `sudo()`（见 enroll.py 文件头注释「所有读走 sudo()」），业务功能不会因此变哑。

---

### F9 —— 【中】内部账号可遍历读取任意附件字节（`/web/content/<id>`）

**证据**（本地全量 1030 条 ir.attachment 逐条实测 + 再抽样复核）

| 样本 | 匿名 | 学生 | 内部（faculty@local） |
|---|---|---|---|
| public=false 附件（抽样 40） | `/web/content` 200 命中 **0/40** | 0 | **40/40 真实字节** |
| public=true 附件（抽样 40） | `/web/content` 200 命中 **39/40**（设计内：网站素材） | 同 | 40/40 |
| id 1024（作业附件） | 404 / 占位图 | 404 | `/web/content/1024` = 32B 真实文本 |
| id 1233（资料库 PDF） | 404 / 占位图 | 404 | `/web/content/1233` = `%PDF-1.4` 真实 PDF |
| id 1011（讨论频道图片） | 404 / 占位图 | 404 | 404（宿主 ACL 拦住） |

- 匿名 `/web/image/<id>` 对**无权**附件返回 **200 + 6078 字节固定占位图**（sha1 恒定），
  **不是泄漏**，但极易在扫描器或人工复核里被误判为「可下载全部附件」，建议在巡检脚本与后续报告里写明这一点。
- 真正的边界是：**任意 share=False 的内部账号都能按 id 递增遍历 `/web/content/<id>` 取到全部附件**，
  包括学生作业提交（`op.assignment.sub.line`）与资料库文件（`edu.download.file`），
  因为 `ir.attachment` 的读权限跟随宿主模型 ACL，而宿主模型对 `base.group_user` 是放开的。
- 门户 / 学生 / 家长被正确拦截（作业附件走控制器 `/my/assignment/sub/<sid>/file` 且带归属校验）。

**风险等级**：**中**。

**修复建议**：给 `ir.attachment` 增加 ir.rule（按 `res_model` 白名单 + 宿主记录归属），
或对敏感宿主模型收紧 `base.group_user` 的读权限。资料下载中心已有 `_can_download()` 与确认门禁，
把这条边界**下沉到模型层**即可。

---

### F10 —— 【中】凭据与配置：ir.config_parameter 明文存放多项秘密，且 edu_telegram 实际已装在生产

**证据（只列 key 名与长度，不打印 value）**

| key | 本地 | 生产 | 说明 |
|---|---|---|---|
| database.secret | 36 字符明文 | 36 字符明文 | Odoo 会话 / 签名密钥 |
| edu_telegram.bot_token | 46 字符明文 | **46 字符明文** | Telegram 机器人 token，可冒充机器人发消息 |
| edu_telegram.webhook_secret | 32 字符明文 | **32 字符明文** | |
| edu_telegram.admin_key | 10 字符明文（值形如 ADMIN-2026，**弱且可猜**） | 10 字符明文 | |
| edu_tg_bind.token | 46 字符明文 | **46 字符明文** | |
| edu_tg_bind.webhook_secret | — | 44 字符明文 | |
| edu_feedback.fp_key / admin_chat_id | — | 存在（32 / 10 字符） | **匿名意见箱，本次未做任何探测** |
| mail.web_push_vapid_private_key | 43 字符明文 | 43 字符明文 | 推送私钥 |
| mail.default.from | scrtsschool@gmail.com | 同 | 公开联系方式，非秘密 |

- `ir.config_parameter` 默认只有 `base.group_system` 可读。本次实测 `group_system` 持有者：
  **本地 = admin(id 2) 一人；生产 = admin(id 2) 一人**（`__system__` 已停用）。这一层是干净的。
- 但**任何能读 DB 或读备份的人**都能直接看到上述明文密钥；备份一旦外流即等于机器人被接管。
- **重要事实纠正**：`edu_telegram` 与 `edu_tg_bind` 在**生产库中 state=installed**
  （edu_telegram 版本 19.0.3.2），与 `docs/code-map.md` 里「edu_telegram 从未部署、2026-09-17 已退役」的记载不一致。
  这套「能发注册码 / 能发通知」的机器人代码在生产是活的，它的 token / secret / admin_key 就是生产凭据。

**风险等级**：**中**（取决于 DB / 备份暴露面；凭据本身明文且 admin_key 弱）。

**修复建议**
1. 密钥类参数迁到环境变量 / secret 管理，或至少使用加密存储；`edu_telegram.admin_key` 立即改 32 位随机值。
2. 生产停用或卸载不再使用的 `edu_telegram`，或明确登记为「在用」，并据此重估 code-map 的退役结论。
3. 轮换所有曾进仓库 / 日志的 bot token 与 webhook secret。

---

### F11 —— 【低】门户页面内部字段暴露面（实测干净）

**证据**：以 stu / parent 两个会话逐页扫描 12 个门户页（`/student/profile`、`/my/contacts`、`/my/home`、`/my/apps`、
`/my/messages`、`/my/messages/2`、`/my/fees`、`/my/child/5`、`/my/telegram`、`/downloads`、
`/my/points/me`、`/my/checkins`），匹配邮箱正则、手机号正则与 `data-uid / data-partner-id` 等属性：

- 邮箱：**0 处**（门户页面不渲染邮箱）
- 手机号：仅 `/student/profile` 与 `/my/contacts` 各 1 处 `13800001234`，经核对是**本人**（partner 35 = 王小明）的号码，不是他人
- 内部 id：无 `data-xxx-id` 属性外露
- 通讯录（`/my/contacts`）学生视角只渲染本人 + 管理员，**其他学生姓名 0 命中**

**风险等级**：**低**（此维度干净）。**修复建议**：无需动作；把上述正则扫描固化成回归脚本即可。

---

### F12 —— 【低】其余无门禁路由复核结论

| 路径 | 实测 | 判定 |
|---|---|---|
| `/library/media/info/<mid>`（batch2.py:1384） | auth=user，只判存在 | 低：op.media 是馆藏公开数据；若将来含内部资料需补可见范围 |
| `/alumni/job/list`（roles.py:1302） | auth=user，返回全部 edu.alumni.job | 低：招聘信息本就公开（`/alumni/jobs` 是 public 同数据） |
| `/my/child`（roles.py:259） | 学生访问返回 200 家长页（空孩子列表） | 低：**无数据泄漏**，属缺门禁的体验问题，建议补 redirect |
| `/my/academic-calendar`、`/meeting/information`、`/online/meeting` | 全空态 / 校历 | 无 |
| `/my/dms`、`/my/asset-request`、`/my/thesis`、welfare.py 的 `/my/checkin*` | 303 兼容跳转桩 | 无 |
| `/my/telegram`、`/my/telegram/new_code` | 只返回**本人**绑定码与会话 | 低：不算越权，但生产是否该向学生暴露 Telegram 绑定面，建议业务确认 |
| `/eval/review`（edu_eval:195） | 学生访问 200「评教填答」空态 | 无数据泄漏 |
| `/my/marks` `/my/rollcall`（edu_telegram） | 学生访问 200，正文只有「仅教师可点名 / 录入成绩」提示 | 无数据泄漏（但用了 200 而非 403，语义不清晰） |


---

## 5. 权限模型实况速查

### 5.1 持有 base.group_system 的账号

| 环境 | 账号 | 说明 |
|---|---|---|
| 本地 | `admin` (id 2) | `__system__`(id 1) 已停用，不计 |
| **生产** | `admin` (id 2) | `__system__` 已停用，不计 |

生产共 24 个启用账号：**21 个门户账号（share=True，全是学生）+ 3 个内部账号（admin / backoffice@local / jiaowu@local 与 teacher@local 一类）**。
即管理员面收得很紧，**问题不在「谁有后台权限」，而在「门户账号被 ACL 授予了太多模型级的读写」**。

### 5.2 门户（base.group_portal）对 edu 模型的 ACL 一览（生产，17 条）

| 模型 | r | w | c | u | 是否有 ir.rule |
|---|---|---|---|---|---|
| edu.leave | 1 | 0 | 0 | 0 | **无** |
| edu.grievance | 1 | 0 | 0 | 0 | **无** |
| edu.daily.checkin | 1 | 0 | 0 | 0 | **无** |
| edu.placement.offer | 1 | 0 | 0 | 0 | **无** |
| edu.point.log | 1 | 0 | 0 | 0 | **无** |
| edu.student.skill | 1 | 0 | 0 | 0 | **无** |
| edu.quiz | 1 | 0 | 0 | 0 | **无** |
| edu.checkin.type | 1 | 0 | 0 | 0 | **无** |
| edu.fee.category | 1 | 0 | 0 | 0 | **无** |
| edu.admin.eval.item | 1 | 0 | 0 | 0 | **无** |
| edu.admin.eval.template | 1 | 0 | 0 | 0 | **无** |
| **edu.favorite** | 1 | **1** | **1** | **1** | **无** |
| **edu.notify.pref** | 1 | **1** | **1** | **1** | **无** |
| edu.admin.eval.score | 1 | 1 | 1 | 0 | 有（2 条） |
| edu.certificate | 1 | 0 | 0 | 0 | 有 |
| edu.checkin.record | 1 | 0 | 0 | 0 | 有 |
| edu.journal.entry | 1 | 0 | 0 | 0 | 有 |

结论：**17 条门户 edu 权限里 13 条没有行规则，其中 2 条还给了写权限**。
答案很直白——不是「门户读得太多」这一层的问题，而是「读了却没有行过滤」。

### 5.3 ir.rule 兜底实况

- 全库共 338 条 ir.rule，其中 **edu 开头模型只有 10 条**，覆盖 7 个模型。
- 覆盖良好的对照组（可照抄）：`edu.certificate` / `edu.checkin.record` / `edu.journal.entry` 用的是
  `[('student_id.user_id', '=', user.id)]`；`edu.message` 用的是 `['|',('sender_id','=',user.id),('recipient_id','=',user.id)]`（且 `global=True`）。
- `custom_addons/edu_portal/security/` **没有 security.xml**，是这次缺口的直接原因。

---

## 6. 最高危的 3 条

1. **F1 · edu 模型缺 ir.rule，任意门户账号一条 RPC 读走全校数据**（严重）
   已实测跨用户读成立（parent uid=10 读到 uid=8 的 6 行 edu.notify.pref、12 行 edu.leave、22 行 edu.grievance），
   生产有 21 个门户账号、ACL 与规则与本地逐条一致，且 edu.favorite / edu.notify.pref 门户还是可写可删。
   **这是「别人来偷资料」最短的一条路。**

2. **F4 · 登录端点零速率限制（base.login_cooldown 是死配置）**（高）
   13 次连续失败 0.02–0.10 秒无一被拦；生产把参数配好了却不生效。
   叠加生产 21 个「login 即学生邮箱」的账号名，在线爆破是现实威胁。

3. **F3 + F2 · 匿名学生名册 + 任意非学生账号可枚举读选课单**（高）
   `/alumni` 在生产匿名渲染 12 个真实学生姓名（已复现）；
   `/subject/registration/data/<rid>` 让家长 / 教师 / 任何无学生档案的账号读到任意学生的选课注册单。

> 紧随其后的是 **F9**（内部账号可遍历读全部附件字节）与 **F5**（招生 PII 进日志）——
> 两条都是「拿到一个内部或低权限账号后能量被放大」的类型。

---

## 7. 建议的修复顺序

**第 1 天（不写代码，先止血）**
1. Cloudflare / nginx 对 `/web/login`、`/register`、`/web/register/submit`、`/apply/submit`、
   `/campus/jobs/*/apply` 加限速 → 直接解掉 F4 与 F6 的一半。
2. 生产把 `/alumni` 临时下线或改成静态页，直到 F3 修好。
3. 生产确认并轮换 `edu_telegram` 与 `edu_tg_bind` 的 token / secret，`admin_key` 改随机。

**第 2 天（一个 PR 解决最严重的结构问题）**
4. 补 `custom_addons/edu_portal/security/security.xml`：为 5.2 表里**没有 ir.rule 的模型逐个写规则**，
   **同时**把门户 ACL 收到 `1,0,0,0`（读仍可、写全关），门户一律走控制器 `sudo()`
   → 解掉 F1 的读与写两条腿。配套加断言脚本，CI 里守住。
5. 修 `/subject/registration/data/<rid>` 的条件短路（F2），并全库搜同型写法。

**第 1 周（把门禁做成规范）**
6. 收 `base.group_user` 的 1,1,1,1（F8），按「教务 / 管理员可写，其余只读」重写 `ir.model.access.csv`。
7. `_is_internal()` 换成 `privileged_staff()`（F7），全仓搜 `_is_internal()` 复核。
8. 给 `ir.attachment` 加行规则，或收紧敏感宿主的 `group_user` 读权限（F9）。
9. 删掉 edu_apply 的 `_DBG_COLLECT` 日志（F5），并加一条「仓内 WARNING 日志不得记录请求值」的检查。
10. 实装 reCAPTCHA 或改人工审核，并统一邀请码错误文案（F6）。

**第 1 个月（制度层）**
11. 把「公开页数据源必须显式过滤 + 明确可公开字段」写进 `docs/dev-workflow.md` 的六步闸门。
12. 密钥迁出 `ir.config_parameter`（F10）；停用无用模块。
13. 增加定期越权回归：本文第 2 节的表格 + 3.3 的 RPC 矩阵，做成 `tests/` 下的脚本，每次部署后跑。

---

## 8. 未验证项（诚实清单）

1. **生产未用真实门户账号做越权实测** —— 没有（也不应有）生产学生凭据，且不得用生产账号做探测性写入。
   F1 的生产结论由「本地实测成立」+「生产 ir.rule / ACL 与本地逐条 SQL 比对一致」共同推理得出，**非直接实测**。
   若需铁证，请提供一名测试学生账号，可在生产重跑 3.3 的**纯读**矩阵。
2. **F1 的写侧未实测**：edu.favorite / edu.notify.pref 的越权 create / write / unlink 是按 ACL 推断，
   遵守红线（不得写他人数据），未发起任何写请求。
3. **edu_feedback / 生产匿名意见箱完全未探测**（红线）。本次只从 ir.config_parameter 看到它存在（fp_key / admin_chat_id）。
4. **`/telegram/webhook`（edu_telegram）与 `/telegram/report/<token>` 未做 payload 探测** —— 前者属地雷区
   （可能与匿名意见箱共路径）。仅代码审读：`edu_tg_bind` 的 `/telegram/tgb/webhook` 是 **fail-closed**
   （secret 未配一律 403，`hmac.compare_digest` 恒时比较），质量明显好于被退役的 v2.2 `edu_telegram`
   （其写法是 `if secret and got != secret`，**未配 secret 时谁都能打**）；生产已确认 secret 已配（32 字符）。
5. **前端 JS / OWL 侧权限**：只审了服务端路由与模型，客户端渲染前的权限判断未覆盖。
6. **会话安全**：Cookie 属性、session 固定、2FA（auth_totp 是否可用）、密码强度策略未纳入本次范围。
7. **邮件外发**：`_notify()` 走 mail.mail，发件人 / 收件人伪造与 SPF / DKIM 属服务器层，未测。
8. **`/web/dataset/call_button`、`/web/action/load` 等其它 JSON 路由**未逐条探测
   （本次只验证 `call_kw` 这一条主路径，已足够证实 F1）。
9. **本地 DB 只有 1 名学生有业务数据**，因此「跨学生」的控制器级越权无法在同一库内构造；
   但 F1 的跨用户证据取自「parent(uid=10) 读到 uid=8 的行」这一真实跨用户场景，不受该限制影响。
10. **`edu_schedule` 的批量排课 / 停课日**只做了门禁层面核对（非教务处 303 回 /my/home），未做业务逻辑审计。
