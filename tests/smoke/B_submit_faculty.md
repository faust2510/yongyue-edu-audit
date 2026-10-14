# 冒烟测试 B：学生提交 + 教师闭环（写操作级）

- 目标: `http://localhost:8069`（Odoo 19 学校系统复刻，docker `edu19-clone`，库 `edu19`，演示库允许造数）
- 账号: `stu@local`（学生）/ `faculty@local`（教师，内部用户）
- 方法: `requests.Session` + `/web/session/authenticate`，CSRF 从表单页正则提取（范式 `scripts/test_submit_flows.py`）；每项失败重试一次。
- 执行时间: 2026-08-23 16:15:57　|　脚本: `scripts/smoke_b_submit_faculty.py`
- 说明: 所有写操作均为**已造数**（演示数据，标题带「可删」）；T6 成绩为**原值回写**以避免污染演示分数。

| 项目 | 方法 | 预期 | 实际 | 结果(PASS/WARN/FAIL) | 证据/备注 |
|---|---|---|---|---|---|
| S1 学生请假提交 | POST /my/time_off/save | URL含box=submitted；GET /my/time_off 出现 SLR\d{6} | 提交成功且列表出现 SLR 单号 | PASS | submit→200 url含box=submitted=True; 列表单号=SLR000006 [已造数] |
| S2 学生申诉提交 | POST /my/grievances/save | 成功标志同上；GET /my/grievances 出现标题 | 提交成功且列表出现标题 | PASS | submit→200 box=submitted=True 列表含标题=True [已造数] |
| S3 学生换课申请 | POST /course/change/request/save | 成功标志同上；页面回显 SR\d{4} 或「已提交」 | 提交成功且回显 SR 单号/已提交 | PASS | course_id=13 submit→200 box=submitted=True 回显SR=SR0008 [已造数] |
| T4 教师请假审批 | POST /leave/set_state(state=approved) | 渲染审批列表；批准后状态变化、移出待审 | 状态变为已批准且移出待审 | PASS | 目标leave_id=19(新提交SLR) 复核: 移出待审=True 学生页[SLR000006]最近状态标签=已批准 [已造数:改状态] |
| T5 教师考勤点名 | POST /attendance/save (+非法参数对照) | 非5xx、redirect含saved=1；非法参数 error=1 非白屏 | 合法保存 saved=1; 非法参数跳转 error=1 | PASS | batch=8 course=18 date=2026-08-23 学生行=1 合法→200 url含saved=1=True; 非法→200 url=error=1 [已造数:考勤表] |
| T6 教师成绩录入 | POST /grading/save | redirect saved=1&scount≥1 且分数回显 | 成绩保存并回显 | PASS | exam_id=11 attendee=11 原值回写=92 (不改演示数据) redirect含saved=1&scount=1=True 回显=True [已造数:原值写入] |
| T7 教师发布作业 | POST /assignment/publish_save | 302→/student/assignment/details；学生端出现该作业 | 创建成功，学生端可见 | PASS | subject=35 type=1 course=18 batch=8 POST→303 Location=/student/assignment/details 学生端详情页→200 含标题=True [已造数] |
| T8 教师发布公告 | POST /notice/publish_save | 跳转布告栏；学生会话 /my/notice_board/notice 出现公告 | 公告创建成功且学生布告栏可见 | PASS | 教师跳转布告栏=True 学生端含标题=True [已造数] |
| T9 应用菜单 | GET /openeducat/apps_menu | 200 且 HTML 含 class="o_app" 卡片若干 | 200 且 o_app 卡片 25 张 | PASS | o_app计数=25 |

**统计: PASS 9/9（WARN 0，FAIL 0）**
