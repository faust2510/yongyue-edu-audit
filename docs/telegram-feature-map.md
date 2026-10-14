# Telegram × 教务功能对接矩阵

> 调查产物（7 个并行子代理：6 组模块源码盘点 + 32 页原站快照逆向）。
> 档位：**TG** = Telegram 内完成；**TG+Web** = bot 触发、网页完成深度操作；**Web** = 仅网页；**暂缓** = 本地缺数据源/企业版专属。
> 现状标注：✅P0 = 已上线；编号即建议实施顺序。

## 评分规则

| 维度 | 判据 |
|---|---|
| ① 纯查询 | 只读，无状态变更 |
| ② 步数 ≤3 | 对话内 1-3 轮完成 |
| ③ 输入形态 | 点选/短文本，无需长文或文件 |
| ④ 否决项 | 视频渲染、大文件上传、防作弊作答、支付 |

①②③全中且无④ → **TG**；简单写操作或需文件 → **TG+Web**；④命中或长表单 → **Web**；本地无模型 → **暂缓**。

## 一、学生侧（核心日常）

| # | 场景 | 数据源 | 档位 | 理由 | 现状 |
|---|---|---|---|---|---|
| 1 | 登录/账户绑定 | edu.telegram.binding + op.telegram.chat | **TG** | 绑定码一次性消费，双因子备用 | ✅P0 |
| 2 | 课表查询 | op.session | **TG** | 纯查询，翻周交互 | ✅P0 |
| 3 | 考试安排 | op.exam | **TG** | 纯查询 | ✅P0 |
| 4 | 成绩查询 | op.result.line | **TG** | 纯查询，分页 | ✅P0 |
| 5 | 成绩单下载 | report_marksheet_report | **TG** | 签名链接发 PDF | ✅P0 |
| 6 | 作业列表 | op.assignment | **TG** | 纯查询 | ✅P0 |
| 7 | 考勤概况 | op.attendance.line | **TG** | 纯查询 | ✅P0 |
| 8 | 图书借阅/逾期 | op.media.movement | **TG** | 纯查询 | ✅P0 |
| 9 | 缴费查询 | op.student.fees.details | **TG** | 纯查询 | ✅P0 |
| 10 | 个人档案 | op.student + student.course | **TG** | 只读展示学籍/班级/学号 | P1-1 |
| 11 | 校历查询 | op.academic.year / term | **TG** | 只读学年学期 | P1-2 |
| 12 | 考勤区间报表 | student.attendance 向导→PDF | **TG** | 输入仅两个日期→发 PDF | P1-3 |
| 13 | 在读证明申请 | bonafide.certificate.wizard→PDF | **TG** | 向导仅一个下拉+短文本，对话内可走完 | P1-4 |
| 14 | 学生证/准考证下载 | report_student_idcard / report_ticket | **TG** | 现成报表转链接 | P1-5 |
| 15 | 周课表总表 PDF | time.table.report(学生版/教师版) | **TG** | 参数=角色自动带出 | P1-6 |
| 16 | 作业提交 | op.assignment.sub.line | **TG+Web** | ⚠️模块无附件字段，仅 description 文本；文件上传是全新开发。bot 做截止提醒+深链，提交在网页 | P2-1 |
| 17 | 图书预约 | op.media.queue(request→accept) | **TG+Web** | 点选书目+日期段，inline 可选书、确认跳网页；审批留馆员 | P2-2 |
| 18 | 选课注册申请 | op.subject.registration(draft→submit→approve) | **TG+Web** | 模型在 core！bot 发起+看状态，勾选科目网页做 | P2-3 |
| 19 | 缴费/支付 | account.move(invoice) | **Web** | 收款走 Odoo accounting 门户；bot 只推「待缴提醒」 | P1-7(提醒) |
| 20 | 转课向导 | student.migrate | **Web** | 多对象级联写入，网页做 | P2 备注 |

## 二、教师侧

| # | 场景 | 数据源 | 档位 | 理由 | 现状 |
|---|---|---|---|---|---|
| 21 | 我的课表 | op.session(faculty_id) | **TG** | 纯查询 | ✅P0 |
| 22 | 负责考试查询 | op.exam(responsible_id) | **TG** | 纯查询 | ✅P0 |
| 23 | 教师借阅查询 | op.media.movement | **TG** | 纯查询 | ✅P0 |
| 24 | 课时统计 | op.faculty.session_count | **TG** | 纯查询 | P1-8 |
| 25 | 点名 | op.attendance.sheet/line 四布尔互斥 | **Web** | 多行勾选+备注，对话效率低 | P2-4 |
| 26 | 成绩录入 | op.exam.attendees(marks) | **Web** | 数字虽短但要逐人核对，安全敏感 | P2-5 |
| 27 | 作业布置/批改 | op.assignment + sub.line(state/marks) | **Web** | 表单+流转按钮；bot 推「新提交」提醒 | P2-6 |

⚠️ 安全隐患：`/openeducat-attendance/take-attendance` 为 `auth=none` 无鉴权批量写路由——独立缺陷，建议第一批就修（加权限+开关）。

## 三、管理员侧

| # | 场景 | 档位 | 说明 |
|---|---|---|---|
| 28 | 全校概览 | **TG** ✅P0 | 各模型 count |
| 29 | 主档维护（课程/批次/科目/专业/院系/教室/时段/活动类型/卡类型/等级配置…38 项中约 30 项） | **Web** | 典型后台表单，TG 无收益 |

## 四、家长侧

| # | 场景 | 档位 | 说明 |
|---|---|---|---|
| 30 | 孩子（课表/成绩/考勤/缴费） | **TG** ✅P0 | 以孩子档案执行 |
| 31 | 待缴/成绩发布提醒 | **TG** | 复用 outbox 推送，P1-9 |

⚠️ 家长可见范围原靠 ir.rule；bot 用 sudo 查询，须在 handler 层复刻「仅本人孩子」过滤（当前实现已按 student_ids 取孩子，扩展时保持）。

## 五、企业版专属 —— 本地无模块，全部暂缓

原站 20 页属 OpenEduCat 企业版，community 无承载模型：

LMS（courses/my-courses）、quiz 在线测验+结果（online-exams/users__result-overview）、OMR 两页、会议两页（meeting/online meeting）、notice_board、grievance 申诉、DMS 文档、student_leave 请假、progression 晋升、certificate 证书、digital-library/my-library 数字资源、asset-request 资产申请、thesis 论文、course_change_request 页面（注：其底层审批模型 subject.registration 在 core 存在，见 #18）。

其中两个「自研性价比高」候选（若二期想补）：**notice_board 轻量版**（一张公告模型+cron 推 TG，布告是最强推送场景）、**student_leave 轻量版**（TG 对话即可完成申请+审批流转）。

另：原站快照全程零上传控件、零视频——「上传资料/看课件」依赖的 LMS/DMS 本就不存在于 community，任何文件上传均为净新增开发。

## 六、三批落地路线

**P1（TG 原生补齐，纯读+现成报表，1 个批次量）**
P1-1 档案 · P1-2 校历 · P1-3 考勤区间报表 PDF · P1-4 在读证明向导 · P1-5 学生证/准考证 · P1-6 周课表 PDF · P1-7 待缴提醒(cron→outbox) · P1-8 教师课时统计 · P1-9 家长提醒复用 · P1-10 课表变更推送（挂钩现成的 op.session.notify_user/_sync_session_followers，邮件模板旁路加 outbox 通道）· 附带：修 take-attendance 鉴权

**P2（触发+深链/轻开发，按需排期）**
P2-1 作业附件字段+提交深链 · P2-2 图书预约对话流 · P2-3 选课注册申请流 · P2-4 点名深链 · P2-5 成绩录入深链+未录提醒 · P2-6 新提交提醒 · P2-7 布告轻模块+推送 · P2-8 请假轻模块+对话审批

**暂缓**：第五节企业清单（除非购企业版或专项自研）

## 数据来源

A1 core/timetable/classroom 38 项 · A2 assignment/admission 16 项 · A3 exam/attendance 25 项 · A4 library 15 项 · A5 fees/parent 15 项 · A6 activity/facility 8 项 · B scrape 32 页逆向。合计 117 项功能卡归并为上表 31 行场景。
