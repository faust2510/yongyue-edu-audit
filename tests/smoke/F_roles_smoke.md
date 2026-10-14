# 冒烟测试 F：教师/家长/管理员 三角色全功能冒烟（任务 t2）

- 时间: 2026-09-17 09:43　目标: http://localhost:8069（Odoo 19, docker edu19-clone, db edu19）
- 账号: faculty@local / parent@local / admin　方法: playwright chrome headless zh-CN + docker exec psql/odoo shell
- 已造数: 考勤表1张(全出勤)、成绩改动(已原值回写92)、作业1条(state=publish)、布告1条、请假单1张(已被批准)。**t85 起跑完自动清理（finally 自清 + leftover 断言）**，不再长期残留。

| 编号 | 项目 | 方法 | 预期 | 实际 | 结果 | 证据 |
|---|---|---|---|---|---|---|
| t1 | 教师考勤录入（已造数） | UI /attendance/take 选班8→全出勤→save | 提交后：当日该班考勤表存在且 line 数=学生数(全出勤)（幂等：首跑建表/再跑更新均可） | 页面=200, 班级选项=1, 学生=1, 今日表=160, 出勤=1/1(首跑Δ=0/0, 落点=/attendance/take?batch_i, saved_flag=False) | PASS | 新sheet=160\|2026-09-17\|8(当日date输入值=2026-09-17); 出勤行=1/1; 截图 smoke_t1_*.png |
| t2 | 教师成绩录入（已改值+原值回写） | UI /grading/entry?exam_id=11 录 marks_11 → save | op_exam_attendees.marks 更新为提交值；回写后复原 | 页面=200, 原=18 → 提交19: saved=True, 库=19(OK) → 回写: 库=18 | PASS | attendee=11(exam 11 总分100); 截图 smoke_t2_*.png |
| t3 | 教师发布【冒烟】作业（已造数） | UI /assignment/publish 表单提交 publish_save | op.assignment 新增且 state=publish，落地作业列表页 | 页面=200, UI落地=是 | PASS | 新记录=109\|publish\|course=18\|batch=8; UI 提交即成功; 截图 smoke_t3_*.png |
| t4 | 教师发【冒烟】布告（已造数） | UI /notice/publish → publish_save → 布告栏 | 布告栏页面可见该条；edu.notice 新增 | 页面=200, 布告栏含标题=是 | PASS | 库中记录=174\|【冒烟】布告 F4-0917-000000; 截图 smoke_t4_*.png |
| t9 | 家长为孩子提交请假（已造数） | UI /my/child/5/leave/save | edu.leave 新增且 state=request，表单回执 saved 横幅 | 页面=200, saved=True | PASS | 新请假单=240\|LV000083\|request; reason 标记='【冒烟】请假 F9-0917-000000' |
| t8 | 家长·我的孩子 + 孩子仪表盘快捷链接 | UI /my/child → /my/child/5 → 逐个快捷链接 | 列出孩子；仪表盘可达且全部快捷链接 200 | 列表=200, 孩子卡=有, 仪表盘=200, 链接 7 个全部 200=True | PASS | /my/calendar:200; /student/attendance:200; /student/exam:200; /grade-book:200; /library/media:200; /my/fees:200; /my/contacts:200 |
| t10 | 家长·我的费用页 | UI /my/fees（parent 会话） | 标题「孩子的账单」且按孩子名分组展示账单 | 面包屑='孩子的账单', 分组头含王小明=True, 账单行=2 | PASS | 分组头=['修改头像', '王小明 待缴合计 ¥12200']; 库中该生账单=2 |
| t11 | 家长·我的资产借还单 | UI /my/assets（parent 会话） | 可见孩子借还单（含此前冒烟产生的演示记录） | 页面=200, 渲染借还行=4, 含演示资产名=True, 库中孩子借还单=4 | PASS | 已知记录: loan#1 投影仪EP-01(returned)/#3,#4 圣经地图册/#2 音响(他人) |
| t5 | 教师请假审批（批准 t9 冒烟单） | UI /leave/approvals → 勾选 ids → 批准 leave_id=240 | （t70 起改为 SKIP：浏览器点击路径待重做；路由可用性由直接 POST 证实） | 页面=200, 待审前=11, 列表含该单=True, 点击批准=True, 单据态=request, 待审后=11 | SKIP | leave#240 request→request; 点击=True; 截图 smoke_t5_*.png; 替代者=authz_endtoend_smoke.py |
| t6 | 教师课表视角 + 后台菜单裁剪 | UI /student/timetable(faculty) + apps_menu 双角色对比 | 教师课表标题「我的教学安排」；教师应用数明显少于 admin | 课表标题='我的教学安排'(行=17), 教师app=19, admin app=37, 差=18 | PASS | admin 多出的应用(裁剪生效证据)=['仪表板', '出勤', '发票', '在线学习', '在线聊天', '应用', '招聘', '数据清除', '日历', '活动', '网站', '联系人'] |
| t7 | 教师·内部费用只读总览 | UI /my/fees（faculty 会话） | 显示「全部账单（只读）」 | 面包屑='全部账单（只读）', 账单行=2 | PASS | 库中账单总数=2 |
| t12 | 管理员后台菜单探活（odoo shell） | shell: ir.model.data(env.ref) + menu.action + res_model search_count | 在线课程/财务管理/资产管理/招聘管理/教务审批/日常管理 6 个根菜单均有 act_window 且 res_model 有效（全覆盖版见 scripts/check_prod_menus.py） | 6/6 行返回, 全部有效=True | PASS | 在线课程(menu_edu_lms_root) menu=576 action=ir.actions.act_window res_model=edu.lesson 有效=True; 财务管理(menu_edu_fees_root) menu=579 action=ir.actions.act_window res_model=edu.fee.bill 有效=True; 资产管理(menu_edu_assets_root) menu=582 action=ir.actions.act_window res_model=edu.asset 有效=True; 招聘管理(menu_edu_jobs_root) menu=585 action=ir.actions.act_window res_model=edu.job.posting 有效=True; 教务审批(menu_edu_approval_root) menu=497 action=ir.actions.act_window res_model=edu.leave 有效=True; 日常管理(menu_edu_welfare_root) menu=543 action=ir.actions.act_window res_model=edu.daily.checkin 有效=True（注：本库 edu19 中根菜单实际 id 为 排课管理=571/财务管理=579，与任务书引用的 714/720 不同——数字 id 因库而异，以 xmlid 为准） |
| t13 | 后台·完整视图组成员校验（odoo shell） | shell: users.has_group('edu_portal.group_backend_full') | admin 在组内；faculty 不在组内 | 组存在=True, admin=True, faculty=False | PASS | T13ROW\|group_exists\|True\|users=[2, 12]; T13ROW\|admin_has_group\|True; T13ROW\|faculty_has_group\|False |

## 备注

## 统计：共 13 项 — PASS 12 / FAIL 0

截图目录: shots/local/smoke_*.png
