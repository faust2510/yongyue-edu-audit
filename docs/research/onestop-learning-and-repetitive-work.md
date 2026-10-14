# 学生一条龙服务 + 会议链接 + 重复劳动自动化 调研

> 日期：2026-09-12 ｜ 取证：优先读**开源项目源码**（Moodle/Canvas/Odoo 在 GitHub 的原始代码），官方文档站作为补充
> ⚠️ 取证限制：`docs.moodle.org` 与 `moodle.org` 全站 **Cloudflare 403**、`archive.org` 超时 → Moodle 结论一律改用 **GitHub 源码原文**；PowerSchool 帮助站为 JS 渲染，只核到栏目 URL；国内厂商官网多为 JS 渲染/不可达，已用官方检索接口与帮助中心 .md 镜像补齐（见 §4）。

---

## 1. "下一步该做什么"：成熟做法

| 做法 | 出处 | 要点 |
|---|---|---|
| Canvas **Modules + 顺序解锁状态机** | [Modules API](https://developerdocs.instructure.com/services/canvas/resources/modules) | `position`、`unlock_at`、`require_sequential_progress`、`requirement_type`(`all`/`one`)、`prerequisite_module_ids`、`state`=**locked/unlocked/started/completed**；条目级 `completion_requirement.type`=`must_view`/`must_contribute`/`must_submit`/`min_score` |
| Canvas To-Do / Planner | [Planner API](https://developerdocs.instructure.com/services/canvas/resources/planner) | To Do 与日程统一入口 |
| Moodle **Timeline 区块** | [blocks/timeline/lib.php](https://github.com/moodle/moodle/blob/main/public/blocks/timeline/lib.php) | 排序 `sortbydates`/`sortbycourses`；筛选 **overdue / next7days / next30days / next3months / next6months**；每课程默认活动数 **5** |
| Moodle 活动完成状态 | [lib/completionlib.php](https://github.com/moodle/moodle/blob/main/public/lib/completionlib.php) | `COMPLETION_INCOMPLETE=0 / COMPLETE=1 / COMPLETE_PASS=2 / COMPLETE_FAIL=3`，落库 `course_modules_completion.completionstate` |
| Moodle 最近访问 | [block_recentlyaccesseditems.php](https://github.com/moodle/moodle/blob/main/public/blocks/recentlyaccesseditems/block_recentlyaccesseditems.php) | 独立区块「Recently accessed items」 |
| Moodle 日历订阅 | [calendar/export_execute.php](https://github.com/moodle/moodle/blob/main/public/calendar/export_execute.php) | `icalexport.ics`；`calendar/export.php` 用 `authtoken=calendar_get_export_token($USER)` 生成**可订阅 URL** |

---

## 2. 会议（Zoom）与课程绑定

| 做法 | 出处 | 要点 |
|---|---|---|
| Moodle `mod_zoom` 数据模型 | [install.xml](https://github.com/jrchamp/moodle-mod_zoom/blob/main/db/install.xml) | 表 `zoom`（join_url、meeting_id、passcode、start_time、duration、recurrence_type、option_waiting_room、grading_method、grade）、`zoom_meeting_details`、`zoom_meeting_recordings`、`zoom_ical_notifications`（`notificationtime`） |
| 一键入会 + 提前可入会 | [lang/en/zoom.php](https://github.com/jrchamp/moodle-mod_zoom/blob/main/lang/en/zoom.php) | `clickjoin`、**`firstjoin`（最早可入会分钟数）**、`displayleadtime`、`unavailablefirstjoin`（"最早可在开始前 {mins} 分钟加入"） |
| 课前提醒（最值得抄） | [classes/task/send_ical_notifications.php](https://github.com/jrchamp/moodle-mod_zoom/blob/main/classes/task/send_ical_notifications.php) | **独立计划任务，每 5 分钟跑一次**；`sendicalnotifications` 开关 |
| 日历双通道 | 同上 | `downloadical` / `addtocalendar`；设了开始时间即自动写入日历 |
| 参会自动判分 | 同 lang 文件 | Upon entry（入会即满分）/ Attendance duration（按时长） |
| Moodle BBB（纯自托管对比） | [mod/bigbluebuttonbn/db/install.xml](https://github.com/moodle/moodle/blob/main/public/mod/bigbluebuttonbn/db/install.xml) | `completionattendance`、`completionengagementtalks/chats/pollvotes`、`openingtime`/`closingtime`、`guestlinkuid` |
| **Odoo 19 原生会议链接位** | [calendar_event.py](https://github.com/odoo/odoo/blob/19.0/addons/calendar/models/calendar_event.py) | `videocall_location`（Meeting URL）、`videocall_source`=[discuss/custom]、路由 `calendar/join_videocall`、`access_token` 邀请令牌 → **把 Zoom 链接存进去即"自定义"模式，零改造** |

### 2.1 集成路径排序（性价比从高到低）
1. **按课节存 join URL + 门户一键跳转**（最低成本，1 字段 + 1 路由）← 本仓采纳
2. **课前提醒 = 独立定时任务**（每 5 分钟扫 T-30min 未提醒课节 → 邮件/Telegram）
3. **每用户 token 化 ICS 订阅**（一次订阅，课表自动进手机）
4. （可选，二期）服务端调 Zoom API 自动建会 —— 见下方额度限制
5. 自研 SDK / 自建会议：无必要

### 2.2 会议 API 额度与限制（已核实）
| 限制 | 数值 | 出处 |
|---|---|---|
| Zoom 账号级速率（Free） | Light 4/s 且 **6000/天**；Medium 2/s 且 **2000/天**；Heavy 1/s 且 1000/天 | [rate-limits](https://developers.zoom.us/docs/api/rate-limits/) |
| **Zoom 会议创建/更新：每用户每天 100 次** | UTC 0 点重置 | 同上 |
| S2S OAuth 前置 | 需**账号级 app**；管理员在 Roles→Advanced features 授权 | [internal-apps](https://developers.zoom.us/docs/internal-apps/) |
| 腾讯会议 | **创建/修改会议：免费版不支持调用**（专业版起） | [能力梯度表](https://cloud.tencent.com/document/product/1095/42407) |
| 腾讯会议免费版时长 | 单场逐步调整为 **40 分钟**；2 人以下不限时 | [官方说明](https://meeting.tencent.com/support/topic/1978/index.html) |
| 飞书预约会议 | **只支持预约最近 30 天内**，且**不生成日程、不显示在日历中** | [reserve/apply](https://open.feishu.cn/document/server-docs/vc-v1/reserve/apply) |

→ **结论：一期只做「按课节存链接 + 定时提醒 + ICS 订阅」，不自研对接任何会议 API。**

---

## 3. 学习资料分层 · 档案成绩页

**资料分层（Odoo eLearning 现成模型）** — [官方文档](https://www.odoo.com/documentation/19.0/applications/websites/elearning.html)：
- **Show course to**：Everyone / Signed In / **Course Attendees** / Anyone with the link
- **Enroll Policy**：Open / **On invitation**（未受邀者可申请 → 生成 To-do 给负责人 Grant/Refuse）/ On payment
- Prerequisites / Prerequisite Of；Certifications

**命名/版本公约（建议，非引用）**：`{范围}-{类别}-{对象}-{版本或日期}`，范围 ∈ {全校,班级,课程,个人}；同名重发**新增版本而非覆盖**，保留下载次数与最近更新人。

**「需确认已读」**：Moodle 核心**无此原语**（未验证到官方实现）→ 需自建确认表；国内有现成范式（见 §4）。

**成绩页最小完整集（Moodle）** — [lib/db/install.xml](https://github.com/moodle/moodle/blob/main/public/lib/db/install.xml)：
`grade_grades`（rawgrade/finalgrade/overridden/locked/feedback/hidden）+ `grade_items`（grademax/gradepass/weightoverride/aggregation）+ `grade_letters`（等级阈值）。
**防信息过载手法**：Single view（逐项）与 Grader report（全表）分离；Canvas 用 `overridden` 标注"已覆盖/未发布"。
→ 建议门户只渲染三层：本学期总览 → 科目条目（权重/得分/及格线）→ 单条目教师反馈；历史学期折叠。
> `docs.moodle.org/en/Single_view` 页面存在但**正文未验证**（Cloudflare 403）。

---

## 4. 国内同类：功能名级证据（钉钉/企微/飞书/校管家/学邦/希沃）

> 钉钉开放平台为 JS SPA，部分功能名取自同域检索接口与 help.dingtalk.io 国际版 .md 镜像（国际版与国内版可能有差异）；企微/飞书加 `.md` 可直取纯文本。

### 4.1 批量审批 / 代理 / 超时
- **钉钉批量审批是付费门槛**：「批量同意或拒绝审批任务」官方原文"**当前接口为 OA 高级版专享接口**" [文档](https://open.dingtalk.com/document/development/api-premiumbatchexecuteprocessinstances)
- **代理审批**：钉钉「代理设置」可配被代理人/代理人/代理时间，可查代理记录、可撤销 [文档](https://help.dingtalk.io/zh/approval/admin-agent-settings.md)
- **超时自动升级**：钉钉「限时审批」事件 [文档](https://developers.dingtalk.com/document/orgapp/events-oa-timeout-plugin-task-msg)、飞书审批超时规则 [文档](https://www.feishu.cn/hc/zh-CN/articles/852878870528)
- **审批模板复用**：企微推荐模板/复制模板/模板分组 [文档](https://open.work.weixin.qq.com/help2/pc/14528)；节点类型含**会签/或签/依次审批** [#14873](https://open.work.weixin.qq.com/help2/pc/14873)
- **飞书批量审批**：官方原文"审批人可以对符合条件的待处理任务进行**批量同意或拒绝**" [文档](https://ae.feishu.cn/hc/zh-CN/articles/686999747964)
- 负面证据：企微「批量审批/代理审批/超时自动转交」**未验证**（帮助中心审批分类无对应条目）；飞书审批开放 API **无批量同意接口**（一次一个 task）

### 4.2 考勤 / 点名
- **钉钉**：异常处理支持**勾选多人批量处理**（可改半年内、正常卡不能改异常、不可撤销）[文档](https://help.dingtalk.io/zh/attendance/modify-abnormal-data.md)；考勤确认可上传 Excel [文档](https://help.dingtalk.io/zh/attendance/admin-quick-start.md)
- **企微**：补卡类型 + 批量处理 [#14866](https://open.work.weixin.qq.com/help2/pc/14866)；API 添加打卡记录一批最多 200 条；**明确不支持批量新增/编辑打卡规则**
- **培训机构范式（最贴近本系统）**：校管家「上课点名」勾选出勤/计费/试听 + 缺勤备注 + 自动统计缺勤次数 + 向家长发签到提醒 [文档](https://wiki.xiaogj.com/docs/ke-biao-he-dian-ming)；**补点名/撤销点名**、**全选/多选学员批量点名** [文档](https://wiki.xiaogj.com/docs/ke-hou-dian-ping)。学邦有「快速点名」「批量考勤」。
- **关键负面结论：钉钉/企微/飞书均无「一键全班出勤」功能名**（它们是员工考勤模型）→ 该范式要到培训机构系统里抄。

### 4.3 成绩录入与留痕
- 校管家：考试管理可选录入或**导入**成绩、查分界面支持**导出**、导入有**导入记录**且**可撤销** [文档](https://wiki.xiaogj.com/docs/kao-shi-guan-li)
- 学邦：成绩管理可批量添加学员后录入并**通知学员**、Excel 标准模板批量导入、**成绩排名可见性开关** [文档](https://www.xuebangsoft.com/help/94918.html)
- **关键负面结论：成绩变更留痕（修改日志）国内三家均未验证**（校管家只有通用"操作日志"且未列明覆盖成绩；希沃仅考勤有"修改记录"）
  → **成绩留痕应抄 Moodle `grade_grades_history`**（`action`/`loggeduser`/`oldid`/`source`/`timemodified`）与专用 history report。

### 4.4 资料发放与已读回执
- **钉钉「班级通知」**："必达家长，**已读未读一目了然**"+"支持**在线手写签字确认**"+"丰富通知模版" [页面](https://page.dingtalk.com/wow/dingtalk/act/classnoti)；**已读回执 API** 出参含 `read(true/false)`+`readTimestamp`（maxResults 500）[文档](https://open.dingtalk.com/document/app/query-bulletin-read-unread-persons-list)
- **企微「学校通知」按班级分发**：to_party 最多 100 个、to_parent/student_userid 各最多 1000、`recv_scope` 0/1/2、去重 `enable_duplicate_check` 默认 1800 秒；**接口无已读回执、无定时字段** [文档](https://developer.work.weixin.qq.com/document/path/92321)
- **飞书广播号**：可配"是否需要用户点击'**我已知悉**'""是否需要设置**定时发送**"、未读加推 [文档](https://www.feishu.cn/hc/zh-CN/articles/654838782631)
- **负面：钉盘/企微微盘/飞书云文档均无「分享有效期/过期自动下架」** → 过期下架需自建（ir.cron 改发布状态）

### 4.5 公告 / 通知
- 钉钉**定时发布**（官方事件原文"如果选择了定时发布，那么会在公告真正被发出来的时候才会触发"）[文档](https://developers.dingtalk.com/document/orgapp/events-blackboard-sent)；消息模板工作通知
- 校管家：公告**可查看已读情况** + 草稿；消息管理可设**接收渠道（微信/短信）+接收人+发送时间** [文档](https://wiki.xiaogj.com/docs/xiao-xi-guan-li)
- 学邦：校区公告含**送达人数/阅读人数**；**排课提醒每天系统自动发送** [文档](https://www.xuebangsoft.com/help/94917.html)

### 4.6 学生自助
- 校管家「预约课」：开放预约后学员可自行预约；可设"上课前几小时不可预约""未达开课人数自动取消" [文档](https://wiki.xiaogj.com/docs/yu-yue-ke)
- 学邦商城：家长可在手机自主完成选课/报名/缴费/选班 [文档](https://www.xuebangsoft.com/help/94378.html)
- **两个共性缺口 = 本系统差异化卖点**：① **ICS/webcal 日历订阅三家全站 0 命中**（钉钉日历有"订阅日历"字样但无 ICS 说明）；② **电子证明/成绩单自助下载三家均未验证提供**

---

## 5. 最值得抄的 10 个做法（收益/成本排序）

1. **Canvas Modules 式顺序解锁**（locked/unlocked/started/completed + prerequisite）→ 学生首页不再迷路。（3 字段 + 1 计算）
2. **Moodle Timeline 分区**（overdue / 7 天 / 30 天，每课程最多 5 条）→ 把"该做的事"顶上来。
3. **按课节的会议链接 + 提前可入会提示**（firstjoin/leadtime）→ 消灭"链接在哪/几点能进"。
4. **课前提醒 = 独立定时任务**（每 5 分钟扫描），而非依赖会议软件自身通知。
5. **一键全班出勤 + 状态集 + QR 自助签到（含轮换/过期）** → 教师端最大痛点。
6. **成绩变更留痕**（history 表 + history report + locked/locktime）→ 争议可追溯。
7. **每用户 token 化 ICS 订阅** → 一次订阅，课表自动同步手机。
8. **资料可见范围 + 报名策略**（Course Attendees / On invitation，申请自动生成负责人 To-do）。
9. **成绩 CSV/XLS 导入导出**（含导入历史）→ 存量迁移与批量录入一次到位。
10. **会议链接复用 Odoo 19 原生 `videocall_location` + `access_token`**（不自建 URL 体系）。

---

## 6. 未验证 / 待确认

- **Moodle 官方文档站全部条目正文因 Cloudflare 403 未能读取**（Activity completion / Restrict access / Bulk user actions / Single view / File resource / Self enrolment 等），相关结论均以 GitHub 源码替代。
- **PowerSchool**：仅核到栏目 URL（[docs.powerschool.com/PSSIS](https://docs.powerschool.com/PSSIS/)），功能名级证据未取得。
- **钉钉开放平台**为 JS SPA，部分功能名取自同域检索接口与**国际版**帮助中心镜像，国内版可能有差异。
- **Zoom 免费账号能否建 S2S OAuth app** 未验证；飞书会议各版本具体免费分钟数未取得（表格前端渲染）；腾讯会议/企微/钉钉会议创建 API 的档位门槛未逐一验证。
- **「需确认已读」在 Moodle/Odoo 的官方原语**：未验证到（国内有现成范式，见 §4.4）。
