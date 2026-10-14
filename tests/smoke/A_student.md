# 冒烟测试 A — 学生角色（stu@local）

- 目标: edu19-clone @ http://localhost:8069（db=edu19），只读 GET
- 判定: HTTP 200、无 Traceback / Internal Server Error、含预期标记之一；失败原样重试一次
- 时间: 2026-09-17 09:45:57

| 路由 | HTTP | 标记命中 | 结果(PASS/WARN/FAIL) | 备注 |
|---|---|---|---|---|
| `/my/home` | 200 | - | WARN | 页面正常渲染(含表格/内容 44555B)但未见标记串; title=工作台；[重试后] |
| `/my` | 200 (303→200) | - | PASS | 跳转至 /my/home；[重试后] |
| `/my/notice_board/notice` | 200 | 布告/通知 | PASS | 命中: 布告/通知 |
| `/student/timetable` | 200 | - | WARN | 页面正常渲染(含表格/内容 70981B)但未见标记串; title=我的课表；[重试后] |
| `/student/attendance` | 200 | 考勤 | PASS | 命中: 考勤 |
| `/student/attendance?page=2` | 200 | 考勤 | PASS | 命中: 考勤; 分页元素: 有 |
| `/student/profile` | 200 | 王小明/档案/个人资料 | PASS | 命中: 王小明/档案/个人资料; 含表格; 空态字样: 暂无 |
| `/student/exam` | 200 | 考试 | PASS | 命中: 考试 |
| `/student/assignment/details` | 200 | 作业 | PASS | 命中: 作业 |
| `/grade-book` | 200 | 成绩 | PASS | 命中: 成绩; 含表格 |
| `/library/media` | 200 | 图书/媒体 | PASS | 命中: 图书/媒体; 空态字样: 暂无 |
| `/library/media?page=2` | 200 | 图书/媒体 | PASS | 命中: 图书/媒体; 分页元素: 有 |
| `/subject/details` | 200 | 科目 | PASS | 命中: 科目; 空态字样: 暂无 |
| `/subject/registration` | 200 | 选课/注册 | PASS | 命中: 选课/注册 |
| `/my-library` | 200 | 我的图书馆 | PASS | 命中: 我的图书馆; 空态字样: 暂无 |
| `/certificate` | 200 | 证书 | PASS | 页面正常渲染，含关键词: 证书 |
| `/meeting/information` | 200 | 会议 | PASS | 命中: 会议; 空态字样: 尚未 |
| `/online/meeting` | 200 | 会议 | PASS | 命中: 会议; 空态字样: 尚未 |
| `/my/academic-calendar` | 200 | 校历/学年 | PASS | 命中: 校历/学年 |
| `/my/asset-request` | 200 | 资产 | PASS | 命中: 资产; 空态字样: 暂无 |
| `/my/dms` | 200 | 文档 | PASS | 命中: 文档; 空态字样: 暂无 |
| `/my/thesis` | 200 | 论文 | PASS | 命中: 论文; 空态字样: 暂无 |
| `/users/result-overview` | 200 | 结果 | PASS | 命中: 结果; 含表格 |
| `/requested/queue/list` | 200 | 队列/请求 | PASS | 命中: 队列/请求; 空态字样: 暂无 |
| `/openeducat-omr/student/exam` | 404 | 考试 | FAIL | HTTP 404；[重试后] |
| `/openeducat-omr/exam-result` | 404 | 考试 | FAIL | HTTP 404；[重试后] |

**统计: 22/26 PASS，2 WARN，2 FAIL**
