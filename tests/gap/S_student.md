# 交互对齐审计 S — 学生门户（/my/home、/student/profile、assignment/exam/library 组）

- 审计人：代理 S ｜ 方式：reference/ + scrape/ 存档 HTML 交互元素提取 vs 本地 Odoo19 (edu19) 登录态抓取
- 账号：stu@local（uid=8 王小明）｜ 本地基准：http://localhost:8069
- 已知勿报项已排除（主题搜索 href="#"、/jobs、/journal/page/N、/my/certificate/download/N、/submited/assignment/list/N）。
- 「缺失(有意)」= 本地代码 `edu_portal/controllers/batch2.py::_DEFAULT_HIDDEN_CARDS` 经系统参数 `edu.portal_hidden_cards` 主动隐藏，非遗漏。

## /my/home（reference/my__home.html + dashboard_categories.json）

| 页面 | 元素(标签) | 原站行为 | 本地现状 | 分类 | 建议 |
|---|---|---|---|---|---|
| /my/home | 六分组卡「进展 Progression」 | 链到 /student/progression 学业进步页 | 卡片存在，但 /student/progression 返回 404，全代码库无该路由 | 死链 | 补 /student/progression 控制器，或暂时把该卡加入 hidden 列表 |
| /my/home | 铃铛提醒「您的图书馆媒体请求已接受」 | 链到 /requested/queue/list（存档实际路径无 /my 前缀；reference 存档里写成 /my/requested/queue/list） | `_ALERT_CARDS` 配置为 `my/requested/queue/list` → 本地 404（真实路由是 `/requested/queue/list`，batch3.py:435）；当前计数 0 未渲染，一旦有借阅队列数据即变死链 | 死链(潜在) | 把 `_ALERT_CARDS`/`_count_for_card` 中 href 改为 `requested/queue/list` |
| /my/home | 六分组卡「即时聊天」 | 链到 /student/livechat/<channel> | 本地 href="#" 无任何动作，且无对应路由（/student/livechat/ → 404） | 空壳 | 社区版无企业 livechat 门户页；建议移入 hidden 列表或接 odoo livechat channel 页 |
| /my/home | 考试列表「查看详情 View Details」 | 打开 /student/exam/data/<id> 考试结果详情页 | 本地链接指向列表页自身（/student/exam），/student/exam/data/* 404，点击无实效 | 空壳 | 补考试结果详情路由并让「查看详情」带上记录 id |
| /my/home | /library/media 三入口「媒体队列 / 媒体采购 / 媒体运动」 | 分别去 /requested/queue/list、/requested/purchase/list、/media/movement/list | 三个链接全部 href="#"；本地 /requested/queue/list 实际存在(200)，另两个路由 404 | 空壳 | 媒体队列直接改指 /requested/queue/list（零成本修复）；采购/运动补路由或删除入口 |
| /my/home | /library/media 媒体标题行（世纪中国文化茎…等 6 条） | 标题链到 /library/media/info/<id> 媒体详情 | 全部 href="#"，/library/media/info/* 404 | 空壳 | 补媒体详情路由，标题行带 id 跳转 |
| /my/home | 六分组卡「Fees Statements 缴费账单」→ /my/invoices | 原站有卡 | 本地默认隐藏（`_DEFAULT_HIDDEN_CARDS`），路由本身 200 | 缺失(有意) | 收费启用后经系统参数 `edu.portal_hidden_cards` 开回 |
| /my/home | 六分组卡「会议 meeting/information」 | 原站 openeducat 组有卡，且为提醒源之一 | 本地路由 200 但首页任何分组都未包含该卡（groups/spec_map 均未引用） | 缺失 | 将 meeting/information 加入资源/社区分组即可（路由已就绪） |
| /my/home | 六分组卡「在线会议 online/meeting」(Zoom) | 原站有卡 | `_OPENEDUCAT_CARDS` 已定义但未加入任何分组 → 永不渲染；路由 200 | 缺失 | 加入分组或删除死配置 |
| /my/home | OMR 两卡(光学MR考试/OMR 考试成绩)、入场 newregistration/info、资产请求 asset-request、您的订单/支付方式/DMS/询价/采购 | 原站均有卡 | 本地全部有意隐藏；其中 /openeducat-omr/*、/my/orders、/my/payment_method、/my/dms、/my/asset-request 路由 200，而 /my/rfq、/my/purchase、/student/newregistration/info 路由 404 | 缺失(有意) | 开回前三者只需改参数；开回 rfq/purchase/入场 需先补路由 |
| /my/home | 铃铛提醒类别：科目注册已批准 / 请假状态已更新 / 资产请求已批准 / 新申诉 / 要审查的报价 | 原站 13 类提醒中这 5 类可真实出现 | `_ALERT_CARDS` 有配置，但 `_count_for_card` 对这些 href 一律返回 None → 永远不触发（placement 已注明社区版无数据，属有意） | 缺失 | 为 op.subject.registration、op.leave、资产/申诉/报价模型补计数逻辑 |
| /my/home | Quick actions 六按钮（时间表/考勤/作业/考试/成绩簿/证书） | data-qa 六项 | 本地六按钮齐全且目标全部 200 | OK | — |
| /my/home | 统计块（KPI×3 + Attendance 大数字 + 课程/进度/学分 chips） | Active courses / Pending assignments / Upcoming exams + Attendance% | 本地等价渲染（在读课程/待完成作业/即将到来的考试 + 考勤% + chips） | OK | — |
| /my/home | 铃铛本体+徽标、hero 搜索框(#searchBox)、accountOffCanvas 抽屉、Edit information→/my/account | 原站齐备 | 本地齐备，/my/account 200 | OK | — |

## /student/profile（scrape/ + reference/student__profile.html）

| 页面 | 元素(标签) | 原站行为 | 本地现状 | 分类 | 建议 |
|---|---|---|---|---|---|
| /student/profile | 七个 tab 锚点（personal_info/placement_offers/job_post_detail/activity_log/fees_details/library/discipline） | 页内 tab 切换 | 七个锚点与区块全部存在（多为「暂无…记录」空态） | OK | — |
| /student/profile | 「Add Your Skill」按钮 | 打开 /student/skill 技能维护页 | 本地无该链接，路由 404，代码库无此路由 | 缺失 | 补 /student/skill 表单页或在模板移除入口 |
| /student/profile | 放置 tab「加入/拒绝」表单 | POST /offer/response/<id> 回复录用 | 本地空态无表单，路由 404 | 缺失 | 社区版无 placement 模块，建议保持空态并文档化 |
| /student/profile | 职位发布 tab「提取」按钮 ×6 | POST /my/withdrawals 撤回申请 | 本地无表单，路由 404 | 缺失 | 同上，随 placement/job 功能一并决策 |
| /student/profile | 费用 tab 发票链接 + PDF 下载 | /my/invoices/<id> 详情、/fees-plan/report/download/<id>?report_type=pdf | 本地空态「暂无费用记录」；/my/invoices/<id> 对非本人发票 303→/my；/fees-plan/report/download/* 404 | 缺失 | 若启用收费需补费用报表下载路由与发票详情可达性 |
| /student/profile | 纪律 tab「道歉表」 | 打开 /student/apology/letter/<id> | 本地空态无链接，路由 404 | 缺失 | 补道歉信页面或维持空态 |

## assignment / exam / library / quiz 组

| 页面 | 元素(标签) | 原站行为 | 本地现状 | 分类 | 建议 |
|---|---|---|---|---|---|
| /student/assignment/details | 作业名称链接（BCA-CC-01-Asg-001） | 打开 /assignment/details/<id> 作业详情 | 本地名称链到 /submited/assignment/list/<id>，/assignment/details/* 404 | 缺失 | 作业说明/附件详情无处可看，建议补详情页或在提交页内展示 |
| /student/assignment/details | sortby×7 / filterby(all,finish,publish) / groupby(none,course_id) / box(publish,submitted,pending) | 筛选排序 | 本地全量一致，box 计数正常 | OK | — |
| /student/exam | sortby×5 / filterby(all,pass,fail) / groupby(none,status) | 筛选排序 | 本地全量一致 | OK | — |
| /my-library | 书卡「Start Reading」/ 封面链接 | /digital-library/read/<id> 在线阅读、/digital-library/material/<id> 素材页 | 本地空态无书卡；两路由均 404 | 缺失 | 数字图书馆阅读器未实现，补 material/read 路由前 my-library 永远空态 |
| /my-library | 搜索框 | GET /digital-library?search=（搜数字资源，含 filter_name） | 本地 GET /library/media?search=（搜馆藏媒体，实测 200 可用） | OK | 行为有偏差（搜的对象不同），如需完全对齐改 action=/digital-library |
| /library/media | sortby×4 / groupby=media_type_id / filterby 全部+各类型 / box(issued,returned) | 筛选排序 | 本地 sortby/groupby/box 齐全；filterby 用本地媒体类型 id(5-9)，实测 200 | OK | — |
| /users/result-overview | 「View Result」 | 打开 /exam/result/<id> 测验结果详情 | 本地行内无任何查看入口；/exam/result/* 404 | 缺失 | 补测验结果详情页并加 View Result 链接 |
| /users/result-overview | sortby×9 / box(passed,failed) / filterby / groupby | 筛选排序 | 本地 sortby×9 与 box 齐全 | OK | — |
| /online-exams | 每个测验卡「开始考试」→ /exam/start/<slug-id> | 公开考试列表直接开考 | 本地 /online-exams 为静态介绍页（内容区零交互）；开考功能整体移至 /quiz，卡片 → /quiz/<id>/take 实测 200 | OK | 功能等价迁移；如需严格对齐可在 /online-exams 列出可考测验 |

## 分类计数

| 分类 | 条数 | 明细 |
|---|---|---|
| OK | 10 | Quick actions×6、统计块、铃铛/搜索/抽屉/Edit information、profile 七 tab、assignment 筛选、exam 筛选、library/media 筛选、my-library 搜索(行为偏差注记)、result-overview 筛选、online-exams(等价迁移) |
| 死链 | 2 | 首页「进展」卡→404；铃铛「图书馆媒体请求」href 配置错(潜在触发) |
| 空壳 | 6 | 即时聊天卡 #、考试查看详情自链、媒体队列/采购/运动 ×#、媒体标题行 ×# |
| 缺失 | 14 | Fees 卡、会议卡、在线会议卡、隐藏卡组(OMR×2/入场/资产/订单/支付/DMS/rfq/采购)、铃铛 5 类提醒、Add Your Skill、offer 加入/拒绝、提取(撤回)、费用 PDF+发票详情、道歉表、作业详情页、数字图书馆 material/read、测验结果详情、(入场/rfq/purchase 路由本身 404 并入隐藏卡组行) |

> 复核命令：`python3 /tmp/audits/check_urls.py`（会话内临时脚本，含全部 44 个目标 URL 的本地状态码）。
