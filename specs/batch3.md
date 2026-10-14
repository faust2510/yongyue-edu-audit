# 批次3 施工规格（剩余静态型页面骨架）

> 前置：批次1/2 模式成熟（controllers/batchN.py + views/batchN.xml + edu_page 骨架）

## 页面清单（12 个，多为列表骨架 + 空态，重点是导航可达、结构对齐）

| 路由 | 标题 | 参考 DOM | 备注 |
|---|---|---|---|
| `/certificate` | Certificates | certificate.html | 卡片网格；无模型 → 空态 |
| `/my-library` | My Library | my-library.html（600K！只取结构） | 数字图书馆分类入口卡 |
| `/course/change/request` | 课程变更请求 | course__change__request.html | 列表 + 申请按钮（空态即可） |
| `/subject/registration` | Subject Registration | subject__registration.html | 同上 |
| `/requested/queue/list` | 图书预约队列 | requested__queue__list.html | op.media.queue 有模型，接真实数据 |
| `/my/time_off` | 休息时间(请假) | my__time_off.html | 新建轻量 `edu.leave`（type/date_from/date_to/state）+ 演示2条 |
| `/meeting/information` | 会议 | meeting__information.html | 空态或简单列表 |
| `/online/meeting` | 在线会议 | online__meeting.html | 空态 |
| `/openeducat-omr/student/exam` | OMR 考试 | openeducat-omr__student__exam.html | 空态卡片 |
| `/openeducat-omr/exam-result` | OMR 考试成绩 | openeducat-omr__exam-result.html | 空态 |
| `/users/result-overview` | 测验结果 | users__result-overview.html | 空态 |
| `/my/grievances` | 申诉 | my__grievances.html | 新建轻量 `edu.grievance` 或空态 |

低优先级（可最后）：`/my/dms`、`/my/asset-request`、`/my/thesis`、`/my/academic-calendar`（academic-calendar 可用 op.academic.year/term 渲染真实数据）

## 额外任务：登录页快捷登录

原站登录页有「Login as」快捷按钮组（Student/Faculty/Parent/Admin/Backoffice），标记：
- 隐藏 form.oe_login_form.d-none 内 `.demo-login-buttons`，每个 `<a class="btn btn-primary demo-login-btn" data-username="..." data-password="...">`
- 页面上另有 OWL 组件 `web.user_switch` 显示入口
本地实现：覆盖 `/web/login` 模板（template inherit web.login，xpath 在表单后插入同构按钮块）；本地对应演示账号 stu@local 等。JS 点击填充提交可用原生小脚本（static/src/js/quick_login.js 注册进 assets_frontend）。教师/家长账号本地暂无，按钮先放 student/admin 两组。

## 工程红线（不变）

- QWeb 禁 `%` 格式化表达式（Odoo 19 装载折叠 %% → 运行时崩）
- search() domain 必填；shell 脚本 savepoint + 结尾 commit
- 输出重定向文件再 grep，严禁 head 截断管道

## 验证

全部新页面 curl 登录后 200 + 标题正确；旧 8 页回归正常。
