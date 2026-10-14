# 逐角色逐页空态矩阵（读数：sweep-v2first-20261002-1849.json，sweep-v2-20261002-1851.json）

## 学生（student）—— 82 条读数

| 路由 | HTTP | 状态 | 空态文案（原样摘录，空白归一） | 判据 |
|---|---|---|---|---|
| `/assess` | 200 | 有内容 | records=1 |  |
| `/assess/fill/2` | 200 | 有内容 | records=4 |  |
| `/assess/my` | 200 | 有内容 | records=1 |  |
| `/assess/my/history` | 200 | 空态-合格 | 本页只显示「已结束」的评估：正在进行中的评估（含尚未打完分的）不在此页显示， 以免展示未完成的结果；评估结束后会出现在这里。 | E2-weak |
| `/certificate` | 200 | 有内容 | records=1 |  |
| `/checkins/stats` | 200 | 有内容 | records=6 |  |
| `/course/change/request` | 200 | 有内容 | records=10 |  |
| `/help` | 200 | 空态-合格 | 还没有账号？ 在线报名 或 使用邀请码注册。 |  |
| `/help/faculty` | 200 | 正文页 | « 返回使用指南 教师版使用指南 面向零基础教师：工作台、排课、批阅与统计的完整操作说明。 一、教师 |  |
| `/help/parent` | 200 | 正文页 | « 返回使用指南 家长版使用指南 面向零基础家长：如何用家长账号了解孩子的在校情况。 一、家长账号如 |  |
| `/help/registrar` | 200 | 正文页 | « 返回使用指南 教务管理版使用指南 面向教务管理人员：开学排课全流程、综合评估与报名表维护。 一、 |  |
| `/help/student` | 200 | 空态-合格 | 文件旁的数字为该资料的累计下载次数；如暂无可下载资料，页面会提示「暂无资料」。 |  |
| `/leave/approvals` | 200 | 有内容 | records=6 |  |
| `/ledger` | 200 | 有内容 | records=6 |  |
| `/ledger/new` | 200 | 有内容 | records=6 |  |
| `/ledger/reimburse` | 200 | 有内容 | records=6 |  |
| `/library/media` | 200 | 空态-合格 | 暂无馆藏媒体。图书上架后将在此处展示书名、作者与版本信息。 | E2-weak |
| `/library/media/info/1` | 200 | 空态-合格 | 暂无馆藏媒体。图书上架后将在此处展示书名、作者与版本信息。 | E2-weak |
| `/meeting/information` | 200 | 空态-合格 | Zoom 会议链接尚未发布。链接配置好后，进入本页将自动跳转 Zoom 会议室。 | E2-weak |
| `/my` | 200 | 有内容 | records=6 |  |
| `/my-courses` | 200 | 需人工看 | （无空态文案） | E0 |
| `/my-library` | 200 | 空态-合格 | 暂无数字馆藏。图书馆上架媒体后，将在此处展示可在线阅读的资源。 |  |
| `/my/academic-calendar` | 200 | 需人工看 | （无空态文案） | E0 |
| `/my/apps` | 200 | 有内容 | records=6 |  |
| `/my/asset-request` | 200 | 空态-合格 | 暂无资产请求。需要教学设备或资料时可在此提交申请。 |  |
| `/my/assets` | 200 | 有内容 | records=5 |  |
| `/my/calendar` | 200 | 空态-合格 | 本月暂无校历事项。 校历事项（开学、考试、停课、活动）由教务处发布，发布后才会出现在这里； 上课安排不在校历里，要看每周课节请打开课表。 查 |  |
| `/my/calendar/new` | 200 | 空态-合格 | 本月暂无校历事项。 校历事项（开学、考试、停课、活动）由教务处发布，发布后才会出现在这里； 上课安排不在校历里，要看每周课节请打开课表。 查 |  |
| `/my/checkin` | 200 | 有内容 | records=6 |  |
| `/my/checkin/board` | 200 | 有内容 | records=6 |  |
| `/my/checkins` | 200 | 有内容 | records=6 |  |
| `/my/contacts` | 200 | 空态-合格 | 本班暂时还没有其他同学。同学名单来自教务的分班与选课， 分班后会自动出现在这里；如果你还没分班，请联系教务处。 |  |
| `/my/courses` | 200 | 有内容 | records=1 |  |
| `/my/courses/46` | 200 | 空态-合格 | 本课程暂无已发布课次。任课教师发布课次后会出现在这里； 在此之前，可以先到课程中心看课程资料与最近安排。 去课程中心 |  |
| `/my/courses/46/rep` | 200 | 有内容 | records=1 |  |
| `/my/courses/lesson/1` | 200 | 有内容 | records=1 |  |
| `/my/dms` | 200 | 空态-合格 | 暂无文档。学坊的文件统一放在「资料下载」：教师与教务处上传的资料都在那里， 按可见范围筛选后即可下载。 去资料下载 |  |
| `/my/documents` | 200 | 有内容 | records=5 |  |
| `/my/documents/enrollment-certificate` | None | 非页面 | 探页失败：Page.goto: Download is starting Call log: - navigating to  | E-PROBE |
| `/my/documents/transcript` | None | 非页面 | 探页失败：Page.goto: Download is starting Call log: - navigating to  | E-PROBE |
| `/my/evaluation` | 200 | 有内容 | records=1 |  |
| `/my/evaluation/new` | 200 | 有内容 | records=1 |  |
| `/my/evaluation/results` | 200 | 有内容 | records=1 |  |
| `/my/evaluation/task/1` | 200 | 有内容 | records=1 |  |
| `/my/fees` | 200 | 有内容 | records=2 |  |
| `/my/grievances` | 200 | 正文页 | 帮助 新手上手清单 我知道了 点击右上角「应用面板」或首页卡片进入各功能 顶部搜索框可查应用入口与作 |  |
| `/my/help` | 200 | 有内容 | records=2 |  |
| `/my/home` | 200 | 有内容 | records=6 |  |
| `/my/journals` | 200 | 有内容 | records=6 |  |
| `/my/messages` | 200 | 有内容 | records=1 |  |
| `/my/messages/2` | 200 | 有内容 | records=1 |  |
| `/my/notice/8` | 200 | 有内容 | records=1 |  |
| `/my/notice_banner` | 200 | 非页面 | 非 HTML 响应（application/json; charset=utf-8） | skip |
| `/my/notice_board/notice` | 200 | 正文页 | 帮助 新手上手清单 我知道了 点击右上角「应用面板」或首页卡片进入各功能 顶部搜索框可查应用入口与作 |  |
| `/my/notify` | 200 | 有内容 | records=1 |  |
| `/my/password` | 200 | 有内容 | records=1 |  |
| `/my/points/me` | 200 | 有内容 | records=4 |  |
| `/my/search` | 200 | 需人工看 | （无空态文案） | E0 |
| `/my/search/suggest` | 200 | 非页面 | 非 HTML 响应（application/json; charset=utf-8） | skip |
| `/my/study` | 200 | 空态-合格 | 本周暂无排课：你的档案班「预备科 · 2026级【演示】」在本周没有任何课节记录（这是本页的筛选结果，不是加载失败）。 |  |
| `/my/study/46` | 200 | 空态-合格 | 暂无成绩记录。任课教师录入并发布成绩后会显示在这里。 |  |
| `/my/thesis` | 200 | 空态-合格 | 暂无论文记录。论文注册与提交尚未在此开放； 如需登记论文题目或提交材料，请联系教务处。 |  |
| `/my/time_off` | 200 | 有内容 | records=12 |  |
| `/online-exams` | 200 | 需人工看 | （无空态文案） | E0 |
| `/online/meeting` | 200 | 空态-合格 | Zoom 会议链接尚未发布。链接配置好后，进入本页将自动跳转 Zoom 会议室。 | E2-weak |
| `/quiz` | 200 | 空态-不合格 | 暂无已发布的测验。 | E1 |
| `/quiz/1/result/1` | 200 | 有内容 | records=1 |  |
| `/quiz/1/take` | 200 | 空态-不合格 | 暂无已发布的测验。 | E1 |
| `/quiz/my` | 200 | 有内容 | records=8 |  |
| `/requested/queue/list` | 200 | 空态-合格 | 暂无媒体预约请求。在图书馆选择图书并加入预约队列后，将在此处展示。 |  |
| `/student/assignment/details` | 200 | 有内容 | records=3 |  |
| `/student/attendance` | 200 | 正文页 | 帮助 新手上手清单 我知道了 点击右上角「应用面板」或首页卡片进入各功能 顶部搜索框可查应用入口与作 |  |
| `/student/exam` | 200 | 正文页 | 帮助 新手上手清单 我知道了 点击右上角「应用面板」或首页卡片进入各功能 顶部搜索框可查应用入口与作 |  |
| `/student/profile` | 200 | 有内容 | records=6 |  |
| `/student/progression` | 200 | 有内容 | records=3 |  |
| `/student/subjects` | 200 | 有内容 | records=1 |  |
| `/student/timetable` | 200 | 空态-合格 | 这一周暂无排课记录。 课表按你所在的班级生成：还没分班、或本周尚未排课时，这里就是空的。 分班与排课由教务在开学时完成，排好后会自动出现；  |  |
| `/subject/details` | 200 | 需人工看 | （无空态文案） | E0 |
| `/subject/enroll` | 200 | 有内容 | records=5 |  |
| `/subject/material/detail/46` | 200 | 有内容 | records=1 |  |
| `/subject/registration` | 200 | 有内容 | records=12 |  |
| `/users/result-overview` | 200 | 有内容 | records=3 |  |

## 学生（空账号夹具）（first）—— 103 条读数

| 路由 | HTTP | 状态 | 空态文案（原样摘录，空白归一） | 判据 |
|---|---|---|---|---|
| `/assess` | 200 | 有内容 | records=1 |  |
| `/assess/faculty/history` | 200 | 有内容 | records=6 |  |
| `/assess/fill/2` | 200 | 有内容 | records=4 |  |
| `/assess/grade/1` | 200 | 有内容 | records=6 |  |
| `/assess/my` | 200 | 有内容 | records=1 |  |
| `/assess/my/history` | 200 | 空态-合格 | 本页只显示「已结束」的评估：正在进行中的评估（含尚未打完分的）不在此页显示， 以免展示未完成的结果；评估结束后会出现在这里。 | E2-weak |
| `/assess/review` | 200 | 有内容 | records=6 |  |
| `/assess/task/1/results` | 200 | 有内容 | records=6 |  |
| `/assess/tasks` | 200 | 有内容 | records=6 |  |
| `/assess/tasks/new` | 200 | 有内容 | records=6 |  |
| `/assess/templates` | 200 | 有内容 | records=6 |  |
| `/assess/templates/new` | 200 | 有内容 | records=6 |  |
| `/attendance/take` | 200 | 有内容 | records=6 |  |
| `/certificate` | 200 | 空态-合格 | 暂未获得结业证书，完成课程并经审核后自动发放。 想查看在修科目与课节进度，可去课程中心。 去课程中心 |  |
| `/checkins/stats` | 200 | 有内容 | records=6 |  |
| `/course/change/request` | 200 | 空态-合格 | 暂无换班申请。提交申请后，处理进度将在此处展示。 |  |
| `/grading/entry` | 200 | 有内容 | records=6 |  |
| `/grading/history` | 200 | 有内容 | records=6 |  |
| `/help` | 200 | 空态-合格 | 还没有账号？ 在线报名 或 使用邀请码注册。 |  |
| `/help/faculty` | 200 | 正文页 | « 返回使用指南 教师版使用指南 面向零基础教师：工作台、排课、批阅与统计的完整操作说明。 一、教师 |  |
| `/help/parent` | 200 | 正文页 | « 返回使用指南 家长版使用指南 面向零基础家长：如何用家长账号了解孩子的在校情况。 一、家长账号如 |  |
| `/help/registrar` | 200 | 正文页 | « 返回使用指南 教务管理版使用指南 面向教务管理人员：开学排课全流程、综合评估与报名表维护。 一、 |  |
| `/help/student` | 200 | 空态-合格 | 文件旁的数字为该资料的累计下载次数；如暂无可下载资料，页面会提示「暂无资料」。 |  |
| `/journals/review` | 200 | 有内容 | records=6 |  |
| `/journals/review/2` | 200 | 有内容 | records=6 |  |
| `/leave/approvals` | 200 | 有内容 | records=6 |  |
| `/ledger` | 200 | 有内容 | records=6 |  |
| `/ledger/new` | 200 | 有内容 | records=6 |  |
| `/ledger/reimburse` | 200 | 有内容 | records=6 |  |
| `/library/media` | 200 | 空态-合格 | 暂无馆藏媒体。图书上架后将在此处展示书名、作者与版本信息。 | E2-weak |
| `/library/media/info/1` | 200 | 空态-合格 | 暂无馆藏媒体。图书上架后将在此处展示书名、作者与版本信息。 | E2-weak |
| `/meeting/information` | 200 | 空态-合格 | Zoom 会议链接尚未发布。链接配置好后，进入本页将自动跳转 Zoom 会议室。 | E2-weak |
| `/my` | 200 | 有内容 | records=6 |  |
| `/my-courses` | 200 | 空态-不合格 | 暂无在读课程。 | E1 |
| `/my-library` | 200 | 空态-合格 | 暂无数字馆藏。图书馆上架媒体后，将在此处展示可在线阅读的资源。 |  |
| `/my/academic-calendar` | 200 | 需人工看 | （无空态文案） | E0 |
| `/my/apps` | 200 | 有内容 | records=6 |  |
| `/my/asset-request` | 200 | 空态-合格 | 暂无资产请求。需要教学设备或资料时可在此提交申请。 |  |
| `/my/assets` | 200 | 有内容 | records=1 |  |
| `/my/calendar` | 200 | 空态-合格 | 本月暂无校历事项。 校历事项（开学、考试、停课、活动）由教务处发布，发布后才会出现在这里； 上课安排不在校历里，要看每周课节请打开课表。 查 |  |
| `/my/calendar/new` | 200 | 空态-合格 | 本月暂无校历事项。 校历事项（开学、考试、停课、活动）由教务处发布，发布后才会出现在这里； 上课安排不在校历里，要看每周课节请打开课表。 查 |  |
| `/my/checkin` | 200 | 有内容 | records=6 |  |
| `/my/checkin/board` | 200 | 有内容 | records=6 |  |
| `/my/checkins` | 200 | 有内容 | records=6 |  |
| `/my/child` | 200 | 需人工看 | （无空态文案） | E0 |
| `/my/child/5` | 200 | 需人工看 | （无空态文案） | E0 |
| `/my/child/5/leave` | 200 | 需人工看 | （无空态文案） | E0 |
| `/my/contacts` | 200 | 空态-合格 | 本班暂时还没有其他同学。同学名单来自教务的分班与选课， 分班后会自动出现在这里；如果你还没分班，请联系教务处。 |  |
| `/my/courses` | 200 | 空态-合格 | 暂无可学课程。这里按你的在修科目展示课次：报课通过、科目生效后会自动出现。 去报课选科 |  |
| `/my/courses/46` | 200 | 空态-合格 | 暂无可学课程。这里按你的在修科目展示课次：报课通过、科目生效后会自动出现。 去报课选科 |  |
| `/my/courses/46/rep` | 200 | 空态-合格 | 暂无可学课程。这里按你的在修科目展示课次：报课通过、科目生效后会自动出现。 去报课选科 |  |
| `/my/courses/lesson/1` | 200 | 空态-合格 | 暂无可学课程。这里按你的在修科目展示课次：报课通过、科目生效后会自动出现。 去报课选科 |  |
| `/my/dms` | 200 | 空态-合格 | 暂无文档。学坊的文件统一放在「资料下载」：教师与教务处上传的资料都在那里， 按可见范围筛选后即可下载。 去资料下载 |  |
| `/my/documents` | 200 | 有内容 | records=2 |  |
| `/my/documents/enrollment-certificate` | None | 非页面 | 探页失败：Page.goto: Download is starting Call log: - navigating to  | E-PROBE |
| `/my/documents/transcript` | None | 非页面 | 探页失败：Page.goto: Download is starting Call log: - navigating to  | E-PROBE |
| `/my/evaluation` | 200 | 有内容 | records=1 |  |
| `/my/evaluation/new` | 200 | 有内容 | records=1 |  |
| `/my/evaluation/results` | 200 | 有内容 | records=1 |  |
| `/my/evaluation/task/1` | 200 | 有内容 | records=1 |  |
| `/my/fees` | 200 | 空态-合格 | 暂无账单。统筹费等应收账单由学坊登记（线下转账后记到账），登记后会出现在这里； 需要垫付报销时，点上方「发起报销」提交申请。 |  |
| `/my/grievances` | 200 | 空态-合格 | 暂无申诉记录。提交申诉后，处理进度将在此处展示。 |  |
| `/my/help` | 200 | 有内容 | records=2 |  |
| `/my/home` | 200 | 有内容 | records=6 |  |
| `/my/journals` | 200 | 有内容 | records=2 |  |
| `/my/messages` | 200 | 有内容 | records=1 |  |
| `/my/messages/2` | 200 | 有内容 | records=1 |  |
| `/my/notice/8` | 200 | 有内容 | records=1 |  |
| `/my/notice_banner` | 200 | 非页面 | 非 HTML 响应（application/json; charset=utf-8） | skip |
| `/my/notice_board/notice` | 200 | 正文页 | 帮助 新手上手清单 我知道了 点击右上角「应用面板」或首页卡片进入各功能 顶部搜索框可查应用入口与作 |  |
| `/my/notify` | 200 | 有内容 | records=1 |  |
| `/my/password` | 200 | 有内容 | records=1 |  |
| `/my/points` | 200 | 有内容 | records=6 |  |
| `/my/points/me` | 200 | 有内容 | records=2 |  |
| `/my/search` | 200 | 需人工看 | （无空态文案） | E0 |
| `/my/search/suggest` | 200 | 非页面 | 非 HTML 响应（application/json; charset=utf-8） | skip |
| `/my/study` | 200 | 空态-合格 | 本周暂无排课：你的档案班（未设置）在本周没有任何课节记录（这是本页的筛选结果，不是加载失败）。 | E2-weak |
| `/my/study/46` | 200 | 空态-合格 | 本周暂无排课：你的档案班（未设置）在本周没有任何课节记录（这是本页的筛选结果，不是加载失败）。 | E2-weak |
| `/my/thesis` | 200 | 空态-合格 | 暂无论文记录。论文注册与提交尚未在此开放； 如需登记论文题目或提交材料，请联系教务处。 |  |
| `/my/time_off` | 200 | 空态-合格 | 暂无休假请求。提交请假申请后，审批状态将在此处展示。 |  |
| `/online-exams` | 200 | 需人工看 | （无空态文案） | E0 |
| `/online/meeting` | 200 | 空态-合格 | Zoom 会议链接尚未发布。链接配置好后，进入本页将自动跳转 Zoom 会议室。 | E2-weak |
| `/quiz` | 200 | 空态-不合格 | 暂无已发布的测验。 | E1 |
| `/quiz/1/result/1` | 200 | 空态-不合格 | 暂无已发布的测验。 | E1 |
| `/quiz/1/take` | 200 | 空态-不合格 | 暂无已发布的测验。 | E1 |
| `/quiz/my` | 200 | 空态-合格 | 还没有参加过测验，去 测验列表 挑一个开始吧。 |  |
| `/registrar/curriculum` | 200 | 有内容 | records=6 |  |
| `/registrar/subject/approvals` | 200 | 有内容 | records=6 |  |
| `/requested/queue/list` | 200 | 空态-合格 | 暂无媒体预约请求。在图书馆选择图书并加入预约队列后，将在此处展示。 |  |
| `/student/assignment/details` | 200 | 空态-合格 | 暂无作业记录。作业由任课教师在课程里发布，发布后这里会显示截止时间与提交状态； 如果你还没有在修科目，先去课程中心看看。 去课程中心 |  |
| `/student/attendance` | 200 | 空态-合格 | 暂无考勤记录。考勤由任课老师每次上课时登记，登记后会按课节显示在这里； 如果课表也还是空的，请先确认自己的排课情况。 查看我的课表 |  |
| `/student/exam` | 200 | 空态-合格 | 暂无考试记录。考试由任课教师在课程中安排，成绩录入后这里会按场次显示得分与等级； 如果你还没有在修科目，先去课程中心看看。 去课程中心 |  |
| `/student/profile` | 200 | 空态-合格 | 暂未登记家长/紧急联系人信息。请把家长或紧急联系人的姓名与电话交给教务处登记，便于紧急情况联系。 |  |
| `/student/progression` | 200 | 空态-合格 | 暂无学业数据。出勤、作业、测验或请假记录产生后，将在此处汇总展示。 |  |
| `/student/subjects` | 200 | 空态-合格 | 暂无在读课程档案。完成报课后，生效科目将在此处展示。 | E2-weak |
| `/student/timetable` | 200 | 空态-合格 | 这一周暂无排课记录。 课表按你所在的班级生成：还没分班、或本周尚未排课时，这里就是空的。 分班与排课由教务在开学时完成，排好后会自动出现；  |  |
| `/subject/details` | 200 | 空态-合格 | 暂无学习科目。报名课程并分配科目后，这里将展示每门科目的学习材料。 |  |
| `/subject/enroll` | 200 | 有内容 | records=4 |  |
| `/subject/material/detail/46` | 200 | 空态-合格 | 暂无学习科目。报名课程并分配科目后，这里将展示每门科目的学习材料。 |  |
| `/subject/registration` | 200 | 空态-合格 | 暂无科目注册记录。完成科目注册后，注册信息将在此处展示。 | E2-weak |
| `/timetable/bulk` | 200 | 有内容 | records=6 |  |
| `/timetable/session/293/impact` | 200 | 有内容 | records=6 |  |
| `/users/result-overview` | 200 | 空态-合格 | 暂无测验结果。完成测验后，成绩分析将在此处展示。 | E2-weak |

## 家长（parent）—— 47 条读数

| 路由 | HTTP | 状态 | 空态文案（原样摘录，空白归一） | 判据 |
|---|---|---|---|---|
| `/help` | 200 | 空态-合格 | 还没有账号？ 在线报名 或 使用邀请码注册。 |  |
| `/help/faculty` | 200 | 正文页 | « 返回使用指南 教师版使用指南 面向零基础教师：工作台、排课、批阅与统计的完整操作说明。 一、教师 |  |
| `/help/parent` | 200 | 正文页 | « 返回使用指南 家长版使用指南 面向零基础家长：如何用家长账号了解孩子的在校情况。 一、家长账号如 |  |
| `/help/registrar` | 200 | 正文页 | « 返回使用指南 教务管理版使用指南 面向教务管理人员：开学排课全流程、综合评估与报名表维护。 一、 |  |
| `/help/student` | 200 | 空态-合格 | 文件旁的数字为该资料的累计下载次数；如暂无可下载资料，页面会提示「暂无资料」。 |  |
| `/leave/approvals` | 200 | 有内容 | records=6 |  |
| `/ledger` | 200 | 有内容 | records=6 |  |
| `/ledger/new` | None | 非页面 | 探页失败：Page.goto: net::ERR_CONNECTION_RESET at http://localhost:806 | E-PROBE |
| `/ledger/reimburse` | 200 | 有内容 | records=6 |  |
| `/library/media/info/1` | 200 | 空态-合格 | 暂无馆藏媒体。图书上架后将在此处展示书名、作者与版本信息。 | E2-weak |
| `/my` | 200 | 有内容 | records=6 |  |
| `/my-courses` | 200 | 需人工看 | （无空态文案） | E0 |
| `/my/asset-request` | 200 | 空态-合格 | 暂无资产请求。需要教学设备或资料时可在此提交申请。 |  |
| `/my/assets` | 200 | 有内容 | records=4 |  |
| `/my/calendar` | 200 | 空态-合格 | 本月暂无校历事项。 校历事项（开学、考试、停课、活动）由教务处发布，发布后才会出现在这里； 上课安排不在校历里，要看每周课节请打开课表。 查 |  |
| `/my/calendar/new` | 200 | 空态-合格 | 本月暂无校历事项。 校历事项（开学、考试、停课、活动）由教务处发布，发布后才会出现在这里； 上课安排不在校历里，要看每周课节请打开课表。 查 |  |
| `/my/checkin` | 200 | 有内容 | records=6 |  |
| `/my/checkin/board` | 200 | 有内容 | records=6 |  |
| `/my/checkins` | 200 | 有内容 | records=6 |  |
| `/my/child` | 200 | 空态-合格 | 暂无已结束的评估记录（进行中的评估不在此处显示）。评估结束后会出现在这里。 | E2-weak |
| `/my/child/5` | 200 | 有内容 | records=7 |  |
| `/my/child/5/leave` | 200 | 需人工看 | （无空态文案） | E0 |
| `/my/contacts` | 200 | 正文页 | 帮助 新手上手清单 我知道了 点击右上角「应用面板」或首页卡片进入各功能 顶部搜索框可查应用入口与作 |  |
| `/my/courses` | 200 | 有内容 | records=1 |  |
| `/my/courses/46` | 200 | 空态-合格 | 本课程暂无已发布课次。任课教师发布课次后会出现在这里； 在此之前，可以先到课程中心看课程资料与最近安排。 去课程中心 |  |
| `/my/courses/46/rep` | 200 | 有内容 | records=1 |  |
| `/my/courses/lesson/1` | 200 | 有内容 | records=1 |  |
| `/my/dms` | 200 | 空态-合格 | 暂无文档。学坊的文件统一放在「资料下载」：教师与教务处上传的资料都在那里， 按可见范围筛选后即可下载。 去资料下载 |  |
| `/my/evaluation` | 200 | 有内容 | records=1 |  |
| `/my/evaluation/new` | 200 | 有内容 | records=1 |  |
| `/my/evaluation/results` | 200 | 有内容 | records=6 |  |
| `/my/evaluation/task/1` | 200 | 有内容 | records=1 |  |
| `/my/fees` | 200 | 有内容 | records=2 |  |
| `/my/help` | 200 | 有内容 | records=2 |  |
| `/my/messages` | 200 | 有内容 | records=1 |  |
| `/my/messages/2` | 200 | 有内容 | records=1 |  |
| `/my/notice/8` | 200 | 有内容 | records=1 |  |
| `/my/notice_banner` | 200 | 非页面 | 非 HTML 响应（application/json; charset=utf-8） | skip |
| `/my/notify` | 200 | 有内容 | records=1 |  |
| `/my/password` | 200 | 有内容 | records=1 |  |
| `/my/search` | 200 | 需人工看 | （无空态文案） | E0 |
| `/my/search/suggest` | 200 | 非页面 | 非 HTML 响应（application/json; charset=utf-8） | skip |
| `/my/study` | 200 | 空态-合格 | 本周暂无排课：孩子的档案班「预备科 · 2026级【演示】」在本周没有任何课节记录。 |  |
| `/my/study/46` | 200 | 空态-合格 | 暂无成绩记录。任课教师录入并发布成绩后会显示在这里。 |  |
| `/my/thesis` | 200 | 空态-合格 | 暂无论文记录。论文注册与提交尚未在此开放； 如需登记论文题目或提交材料，请联系教务处。 |  |
| `/online-exams` | 200 | 需人工看 | （无空态文案） | E0 |
| `/student/timetable` | 200 | 空态-合格 | 这一周暂无排课记录。 孩子的课表按班级生成：孩子还没分班、或本周尚未排课时，这里就是空的。 分班与排课由教务在开学时完成；可到孩子仪表盘确认 |  |

## 教师（faculty）—— 57 条读数

| 路由 | HTTP | 状态 | 空态文案（原样摘录，空白归一） | 判据 |
|---|---|---|---|---|
| `/assess` | 200 | 有内容 | records=1 |  |
| `/assess/faculty/history` | 200 | 空态-合格 | 本页只显示「已结束」的评估：正在进行中的评估（含尚未打完分的）不在此页显示， 以免展示未完成的结果；评估结束后会出现在这里。 | E2-weak |
| `/assess/grade/1` | 200 | 有内容 | records=2 |  |
| `/assess/review` | 200 | 有内容 | records=3 |  |
| `/assess/task/1/results` | 200 | 有内容 | records=3 |  |
| `/attendance/take` | 200 | 需人工看 | （无空态文案） | E0 |
| `/checkins/stats` | 200 | 有内容 | records=9 |  |
| `/grading/entry` | 200 | 需人工看 | （无空态文案） | E0 |
| `/grading/history` | 200 | 有内容 | records=50 |  |
| `/help` | 200 | 空态-合格 | 还没有账号？ 在线报名 或 使用邀请码注册。 |  |
| `/help/faculty` | 200 | 正文页 | « 返回使用指南 教师版使用指南 面向零基础教师：工作台、排课、批阅与统计的完整操作说明。 一、教师 |  |
| `/help/parent` | 200 | 正文页 | « 返回使用指南 家长版使用指南 面向零基础家长：如何用家长账号了解孩子的在校情况。 一、家长账号如 |  |
| `/help/registrar` | 200 | 正文页 | « 返回使用指南 教务管理版使用指南 面向教务管理人员：开学排课全流程、综合评估与报名表维护。 一、 |  |
| `/help/student` | 200 | 空态-合格 | 文件旁的数字为该资料的累计下载次数；如暂无可下载资料，页面会提示「暂无资料」。 |  |
| `/journals/review` | 200 | 有内容 | records=6 |  |
| `/journals/review/2` | 200 | 有内容 | records=1 |  |
| `/leave/approvals` | 200 | 有内容 | records=12 |  |
| `/ledger` | 200 | 有内容 | records=9 |  |
| `/ledger/new` | None | 非页面 | 探页失败：Page.goto: net::ERR_CONNECTION_RESET at http://localhost:806 | E-PROBE |
| `/ledger/reimburse` | 200 | 有内容 | records=9 |  |
| `/library/media/info/1` | 200 | 空态-合格 | 暂无馆藏媒体。图书上架后将在此处展示书名、作者与版本信息。 | E2-weak |
| `/my` | 200 | 有内容 | records=9 |  |
| `/my-courses` | 200 | 需人工看 | （无空态文案） | E0 |
| `/my/asset-request` | 200 | 空态-合格 | 暂无资产请求。需要教学设备或资料时可在此提交申请。 |  |
| `/my/calendar` | 200 | 空态-合格 | 本月暂无校历事项。 校历事项（开学、考试、停课、活动）由教务处发布，发布后才会出现在这里； 上课安排不在校历里，要看每周课节请打开课表。 查 |  |
| `/my/calendar/new` | 200 | 有内容 | records=1 |  |
| `/my/checkin` | 200 | 有内容 | records=9 |  |
| `/my/checkin/board` | 200 | 有内容 | records=7 |  |
| `/my/checkins` | 200 | 有内容 | records=9 |  |
| `/my/contacts` | 200 | 正文页 | 帮助 新手上手清单 我知道了 点击右上角「应用面板」或首页卡片进入各功能 顶部搜索框可查应用入口与作 |  |
| `/my/courses` | 200 | 有内容 | records=50 |  |
| `/my/courses/46` | 200 | 空态-合格 | 本课程暂无已发布课次。任课教师发布课次后会出现在这里； 在此之前，可以先到课程中心看课程资料与最近安排。 去课程中心 |  |
| `/my/courses/46/rep` | 200 | 有内容 | records=50 |  |
| `/my/courses/lesson/1` | 200 | 有内容 | records=1 |  |
| `/my/dms` | 200 | 空态-合格 | 暂无文档。学坊的文件统一放在「资料下载」：教师与教务处上传的资料都在那里， 按可见范围筛选后即可下载。 去资料下载 |  |
| `/my/evaluation` | 200 | 有内容 | records=1 |  |
| `/my/evaluation/new` | 200 | 有内容 | records=1 |  |
| `/my/evaluation/results` | 200 | 空态-合格 | 暂无已结束的评估结果。评估结束（打分完成）后会在这里出现；进行中的评估不在本页显示。 | E2-weak |
| `/my/evaluation/task/1` | 200 | 有内容 | records=1 |  |
| `/my/fees` | 200 | 空态-合格 | 暂无账单。统筹费等应收账单由学坊登记（线下转账后记到账），登记后会出现在这里； 需要垫付报销时，点上方「发起报销」提交申请。 |  |
| `/my/help` | 200 | 有内容 | records=2 |  |
| `/my/home` | 200 | 有内容 | records=9 |  |
| `/my/messages` | 200 | 有内容 | records=1 |  |
| `/my/messages/2` | 200 | 有内容 | records=1 |  |
| `/my/notice/8` | 200 | 有内容 | records=1 |  |
| `/my/notice_banner` | 200 | 非页面 | 非 HTML 响应（application/json; charset=utf-8） | skip |
| `/my/notice_board/notice` | 200 | 正文页 | 帮助 新手上手清单 我知道了 点击右上角「应用面板」或首页卡片进入各功能 顶部搜索框可查应用入口与作 |  |
| `/my/notify` | 200 | 有内容 | records=1 |  |
| `/my/password` | 200 | 有内容 | records=1 |  |
| `/my/points` | 200 | 有内容 | records=4 |  |
| `/my/search/suggest` | 200 | 非页面 | 非 HTML 响应（application/json; charset=utf-8） | skip |
| `/my/study` | 200 | 空态-不合格 | 本周暂无排课：本周没有以你为任课教师的课节。 | E1 |
| `/my/study/46` | 200 | 空态-合格 | 暂无成绩记录。任课教师录入并发布成绩后会显示在这里。 |  |
| `/my/thesis` | 200 | 空态-合格 | 暂无论文记录。论文注册与提交尚未在此开放； 如需登记论文题目或提交材料，请联系教务处。 |  |
| `/online-exams` | 200 | 需人工看 | （无空态文案） | E0 |
| `/registrar/subject/approvals` | 200 | 空态-合格 | 没有符合条件的选课申请。换一个筛选条件可看其他状态的申请；学生提交选课申请后会进入这里。 |  |
| `/student/timetable` | 200 | 空态-合格 | 这一周暂无排课记录。 本周没有你的课节。课表按教务处的排课生成：还没排到你的课时，这里就是空的； 如果应该有课却没显示，请联系教务处核对排课 |  |

## 教务（backoffice）—— 52 条读数

| 路由 | HTTP | 状态 | 空态文案（原样摘录，空白归一） | 判据 |
|---|---|---|---|---|
| `/assess` | 200 | 有内容 | records=2 |  |
| `/assess/faculty/history` | 200 | 有内容 | records=12 |  |
| `/assess/grade/1` | 200 | 有内容 | records=2 |  |
| `/assess/review` | 200 | 有内容 | records=3 |  |
| `/assess/task/1/results` | 200 | 有内容 | records=3 |  |
| `/assess/tasks` | 200 | 有内容 | records=4 |  |
| `/assess/tasks/new` | 200 | 有内容 | records=3 |  |
| `/assess/templates` | 200 | 有内容 | records=23 |  |
| `/assess/templates/new` | 200 | 有内容 | records=1 |  |
| `/grading/history` | 200 | 有内容 | records=50 |  |
| `/help` | 200 | 空态-合格 | 还没有账号？ 在线报名 或 使用邀请码注册。 |  |
| `/help/faculty` | 200 | 正文页 | « 返回使用指南 教师版使用指南 面向零基础教师：工作台、排课、批阅与统计的完整操作说明。 一、教师 |  |
| `/help/parent` | 200 | 正文页 | « 返回使用指南 家长版使用指南 面向零基础家长：如何用家长账号了解孩子的在校情况。 一、家长账号如 |  |
| `/help/registrar` | 200 | 正文页 | « 返回使用指南 教务管理版使用指南 面向教务管理人员：开学排课全流程、综合评估与报名表维护。 一、 |  |
| `/help/student` | 200 | 空态-合格 | 文件旁的数字为该资料的累计下载次数；如暂无可下载资料，页面会提示「暂无资料」。 |  |
| `/leave/approvals` | 200 | 有内容 | records=12 |  |
| `/ledger` | 200 | 有内容 | records=6 |  |
| `/ledger/new` | 200 | 有内容 | records=1 |  |
| `/ledger/reimburse` | 200 | 空态-合格 | 该状态下暂无报销单。报销单由门户提交后进入本审批台；切换上方状态可看其他阶段的单据。 |  |
| `/library/media/info/1` | 200 | 空态-合格 | 暂无馆藏媒体。图书上架后将在此处展示书名、作者与版本信息。 | E2-weak |
| `/my` | 200 | 有内容 | records=12 |  |
| `/my-courses` | 200 | 需人工看 | （无空态文案） | E0 |
| `/my/asset-request` | 200 | 空态-合格 | 暂无资产请求。需要教学设备或资料时可在此提交申请。 |  |
| `/my/calendar` | 200 | 有内容 | records=5 |  |
| `/my/calendar/new` | 200 | 有内容 | records=1 |  |
| `/my/checkin` | 200 | 有内容 | records=12 |  |
| `/my/checkin/board` | 200 | 有内容 | records=7 |  |
| `/my/checkins` | 200 | 有内容 | records=12 |  |
| `/my/courses/46/rep` | 200 | 有内容 | records=50 |  |
| `/my/dms` | 200 | 空态-合格 | 暂无文档。学坊的文件统一放在「资料下载」：教师与教务处上传的资料都在那里， 按可见范围筛选后即可下载。 去资料下载 |  |
| `/my/evaluation` | 200 | 有内容 | records=2 |  |
| `/my/evaluation/new` | 200 | 有内容 | records=2 |  |
| `/my/evaluation/results` | 200 | 有内容 | records=12 |  |
| `/my/evaluation/task/1` | 200 | 有内容 | records=2 |  |
| `/my/help` | 200 | 有内容 | records=2 |  |
| `/my/home` | 200 | 有内容 | records=12 |  |
| `/my/messages` | 200 | 有内容 | records=1 |  |
| `/my/messages/2` | 200 | 有内容 | records=1 |  |
| `/my/notice/8` | 200 | 有内容 | records=1 |  |
| `/my/notice_banner` | 200 | 非页面 | 非 HTML 响应（application/json; charset=utf-8） | skip |
| `/my/notice_board/notice` | 200 | 正文页 | 帮助 新手上手清单 我知道了 点击右上角「应用面板」或首页卡片进入各功能 顶部搜索框可查应用入口与作 |  |
| `/my/notify` | 200 | 有内容 | records=1 |  |
| `/my/password` | 200 | 有内容 | records=1 |  |
| `/my/search/suggest` | 200 | 非页面 | 非 HTML 响应（application/json; charset=utf-8） | skip |
| `/my/study` | 200 | 空态-合格 | 暂无排课 进入本科目 → |  |
| `/my/study/46` | 200 | 空态-合格 | 暂无成绩记录。任课教师录入并发布成绩后会显示在这里。 |  |
| `/my/thesis` | 200 | 空态-合格 | 暂无论文记录。论文注册与提交尚未在此开放； 如需登记论文题目或提交材料，请联系教务处。 |  |
| `/online-exams` | 200 | 需人工看 | （无空态文案） | E0 |
| `/registrar/curriculum` | 200 | 有内容 | records=74 |  |
| `/registrar/subject/approvals` | 200 | 有内容 | records=11 |  |
| `/timetable/bulk` | 200 | 有内容 | records=19 |  |
| `/timetable/session/293/impact` | 200 | 有内容 | records=8 |  |

## 访客（未登录）（guest）—— 6 条读数

| 路由 | HTTP | 状态 | 空态文案（原样摘录，空白归一） | 判据 |
|---|---|---|---|---|
| `/help` | 200 | 空态-合格 | 还没有账号？ 在线报名 或 使用邀请码注册。 |  |
| `/help/faculty` | 200 | 正文页 | « 返回使用指南 教师版使用指南 面向零基础教师：工作台、排课、批阅与统计的完整操作说明。 一、教师 |  |
| `/help/parent` | 200 | 正文页 | « 返回使用指南 家长版使用指南 面向零基础家长：如何用家长账号了解孩子的在校情况。 一、家长账号如 |  |
| `/help/registrar` | 200 | 正文页 | « 返回使用指南 教务管理版使用指南 面向教务管理人员：开学排课全流程、综合评估与报名表维护。 一、 |  |
| `/help/student` | 200 | 空态-合格 | 文件旁的数字为该资料的累计下载次数；如暂无可下载资料，页面会提示「暂无资料」。 |  |
| `/online-exams` | 200 | 需人工看 | （无空态文案） | E0 |

## 合计

- 空态-合格：95 条读数
- 空态-不合格：7 条读数
- 需人工看：22 条读数
