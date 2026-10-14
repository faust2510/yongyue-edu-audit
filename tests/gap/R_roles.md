# 交互对齐审计 R —— 教师端(faculty) + 家长端(parent)

- 审计人：代理 R（只读审计，未改任何业务代码/未重启容器）
- 方法：解析 `reference/roles/faculty/`、`reference/roles/faculty/rendered/`、`reference/roles/parent/` 共 31 个存档，提取 `<a href>`/`<button>`/`<form action>`/onclick/tab/data-bs-toggle 元素；分别以 `faculty@local`、`parent@local` 登录 `http://localhost:8069`（requests，trust_env=False），逐元素核对本地对应页（GET 判定可达性，未做写操作 POST）。
- 已按要求忽略：`/jobs`、`/journal/page/N`、证书下载链。
- 说明：原站存档中 student__* 共享页主区均为 “There are no records.”（家长/教师快照即为空态），本地“未找到当前登录用户对应的学生档案”与之行为对齐，计为 OK。

## 差距清单（非 OK 项）

| 角色 | 页面 | 元素(标签) | 原站行为 | 本地现状 | 分类 | 建议 |
|---|---|---|---|---|---|---|
| 教师 | /my/home | 卡片「进展」(`<a>`) | 跳转学生进展页 `/student/progression` | 卡片存在，链接指向的路由未实现，GET→404 | 死链 | 实现 progression 控制器，或先加入 `edu.portal_hidden_cards` 隐藏 |
| 家长 | /my/home | 卡片「进展」(`<a>`) | 同上 | 同上（家长/教师共用首页模板） | 死链 | 同上 |
| 教师+家长 | /my/home | 卡片「即时聊天」(`<a>`) | 打开 `/student/livechat/` 聊天页 | 渲染为 `href="#"` 纯摆设（代码注释：社区版无对应路由） | 死链(摆设) | 接入 Discuss Livechat 或移除该卡 |
| 教师+家长 | /my/home | 入口卡「会议/在线会议/Fees Statements/您的订单/支付方式/DMS/资产请求/OMR考试/OMR成绩/入场/询价/我们的订单」 | 原站首页均有可点卡片 | 默认被 `_DEFAULT_HIDDEN_CARDS` 整组隐藏；其中 `/my/rfq`、`/my/purchase`、`/student/newregistration/info` 本地连路由都不存在(404)，其余页面可达仅缺入口 | 缺失(有意隐藏) | 用系统参数 `edu.portal_hidden_cards` 按需恢复；为仍缺的 3 个路由补实现 |
| 教师+家长 | /library/media | 按钮「媒体队列」(`<a class=oe-asg-btn>`) | 跳 `/requested/queue/list` | `href="#"` 死锚；而目标页本地已实现(200) | 死链 | 直接把 href 改为 `/requested/queue/list`（零成本修复） |
| 教师+家长 | /library/media | 按钮「媒体采购」(`<a>`) | 跳 `/requested/purchase/list` | `href="#"` 且路由 404 | 死链(页面缺失) | 补采购队列控制器+模板后接线 |
| 教师+家长 | /library/media | 按钮「媒体运动」(`<a>`) | 跳 `/media/movement/list` | `href="#"` 且路由 404（`op.media.movement` 模型已在库内使用） | 死链(页面缺失) | 基于 op.media.movement 补列表页并接线 |
| 教师+家长 | /library/media | 媒体标题链接×29 (`<a class=oe-asg-name>`) | 打开媒体详情 `/library/media/info//<id>` | 全部 `href="#"`，info 详情路由缺失 | 死链(页面缺失) | 实现详情页并把标题接到 `/library/media/info/<id>` |
| 家长(教师本地同款) | /my/notice_board/notice | Tab「Circular/圆形」(`<a class=oe-asg-btn--ghost>`) | 跳 `/my/notice_board/circular`（家长存档直接证据） | `href="#"` 且路由 404 | 死链(页面缺失) | 补 circular 列表页，或移除死 Tab |
| 教师+家长 | /my/notice_board/notice | 公告标题×N (`<a class=oe-att-name>`) | 原站标题不可点（存档中无标题链接） | 本地新增 `href="#"` 假链接，点击无反应 | 摆设 | 去掉 `<a>` 或接公告详情展开 |
| 教师+家长 | /grade-book | 「Download Report」(`<a class=oe-gb-dl title=下载非官方报告>`) | 下载非官方成绩报告 | 本地整页无任何下载按钮/OWL 组件 | 缺失 | 补成绩单导出（即使空态也应保留入口） |
| 教师+家长 | /meeting/information | 搜索框 + 「排序依据：会议」下拉(`?sortby=meeting_id`) | 标准 portal 列表脚手架（存档含 search/sortby 控件） | 替换为静态“Zoom 链接尚未发布”占位文案，无搜索/排序/表格 | 空壳 | 还原列表脚手架，接 op.meeting 数据源 |
| 家长 | /my/child/5 孩子仪表盘 | 快捷卡「时间表/考勤/成绩簿」(`<a>`) | 应查看孩子的课表/考勤/成绩 | 跳共享页后按“登录用户→学生”取数，家长会话恒为“未找到学生档案”空态，形成空循环 | 空壳(风险) | 快捷入口带 child_id 参数或改为仪表盘内嵌分区 |
| 家长 | /my/child/5/leave | 代子女请假表单(POST …/leave/save) | 原站家长经请假流程代子女申请 | 路由与表单已实现，但全站无任何入口链接到它（孤儿页面） | 缺失(入口) | 在孩子仪表盘加「代孩子请假」按钮 |

## 计数

| 分类 | 行数 |
|---|---|
| OK（见下方核对通过项） | — |
| 死链（含 死链/摆设、死链/页面缺失） | 9 |
| 摆设（纯装饰假链接） | 1 |
| 空壳（含 风险） | 2 |
| 缺失（含 有意隐藏、入口缺失） | 2 |

## 核对通过项（OK，抽样列举）

- 教师登录落地 `/openeducat/apps_menu` 200；应用菜单 25 个后端动作 `/odoo/action-*` 抽测均可达（作业/课堂出勤率/教务审批等）。
- 教师五大工作台全部可用：考勤录入 `/attendance/take?course_id=6`→选班加载学生→radio 打勾→`/attendance/save`；成绩录入 `/grading/entry?exam_id=11`→marks 输入→`/grading/save`；发布作业 `/assignment/publish`（科目14/课程6/批次选项齐全）；请假审批 `/leave/approvals` 14 行待审+批准/驳回表单；公告发布 `/notice/publish` 且布告栏页有「发布公告」入口。
- `/my/time_off` 的「创建休假请求」以折叠表单(`/my/time_off/save`)实现，替代原站独立页 `/time_off/request`，交互等效（原站该路由本地 404 不再单列）。
- 列表页搜索/排序/筛选/分组（library/media、notice_board、time_off、student 列表）与原站 sortby/filterby/groupby 语义一致；分页正常。
- 家长 `/my/child`(200)、子卡「查看仪表盘」→`/my/child/5` 仪表盘(200)；`/student/*`、`/grade-book`、`/users/result-overview`、`/subject/*` 等共享页空态与原站存档一致。
- `/my/account`、`/my/security`、`/my/addresses`、`/my/invoices?filterby=overdue_invoices`、`/my/quotes`、`/my/orders`、`/my-library`、`/certificate`、`/quiz`、`/my/academic-calendar` 双角色均 200 可用；通知铃(计数+全部标为已读 `POST /alerts/mark_read`)工作正常（原站分类型提醒卡简化为单一通知链接，属数据驱动简化，不计差距）。

*生成于交互对齐审计（代理 R）；证据脚本输出存于 /tmp/auditR/live_faculty.txt、live_parent.txt。*
