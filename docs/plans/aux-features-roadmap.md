# 高频功能辅助增强包（aux-features）—— 设计路线图
> **状态**：`在研` ｜ **主题**：`辅助增强包路线图` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 2026-08-29 定稿。依据两份侦查：全仓 180 路由功能盘点（17 项缺口 C1-C17）+ 同类系统调研（Moodle/Canvas/PowerSchool/RosarioSIS/Gibbon/Fedena，见 `docs/audit/peer-research.md`）。
> 原则：SSR 友好（服务端生成资源 + 普通链接/表单）、纯新增优先、严格复用既有角色过滤、每批完整闭环后提交。**生产部署等用户本地验收后另行执行。**

## 批次 1：数据出口三件套（只读新增，零数据结构风险）

### 1a 全站 CSV 导出体系（C1）
- 范式：`batch2.py` grade-book CSV（utf-8-sig BOM 防 Excel 乱码）。
- 新增只读导出路由，domain 与原列表页完全一致：
  - 学生：`/student/attendance/export` 考勤、`/my/time_off/export` 请假、`/my/grievances/export` 申诉、`/my/fees/export` 账单、`/my/checkins/export` 打卡、`/my/downloads/mine/export` 下载记录
  - 教师：`/checkins/stats/export` 打卡统计
  - 教务：`/downloads/stats/export` 下载统计
- 各列表页头部加「导出 CSV」按钮，透传当前筛选参数。
- 中文件名走 RFC5987（`filename*=UTF-8''`，与资料下载同名文件下载先例一致）。

### 1b PDF/图片在线预览（C2，参考 Canvas 展示策略）
- `/downloads/file/<id>?inline=1`：pdf/图片白名单内 → `Content-Disposition: inline`；否则维持 attachment。资料页行内加「预览」（浏览器原生渲染 PDF，零 JS）。
- 作业附件 `/my/assignment/sub/<sid>/file?inline=1` 同理。
- 明确不做 Office 原格式预览（需转码链路，第 5 批）。

### 1c iCal 日历订阅（C3，参考 Moodle/Canvas Calendar Feed）
- `res.users.edu_ical_token`（首次访问懒生成，hex 24）。
- 路由 `/my/calendar/ics/<token>`（`auth='public'`，按 token 反查用户；token 不匹配 404）。
- 内容按角色（复用 `calendar.py` 的四源查询思路）：个人课表 op.session（学生按班/教师按任课）、考试、停课日、校历活动、作业截止；`_local_to_utc_naive` 转 UTC；DATE-TIME 用 UTC（Z 后缀），全天事件用 DATE。
- `/my/calendar` 与 `/student/timetable` 页头加「订阅到手机」入口（`?sub=1` 展示 URL 与 iOS/Android/Outlook 说明，纯服务端）。

## 批次 2：提醒补全 + 审批体验 + 考勤防护

- **2a 提醒补全（C14）**：周记批阅（edu_life `life.py` grade）→ 给学生发 `edu.message`；成绩录入 `/grading/save` → 逐生发「新成绩已录入」；作业批改入口侦查后接（后台 write 则挂钩子，范式 `edu_telegram/models/hooks.py`）。全部失败只 `_logger.warning` 不回滚。
- **2b 审批列表对齐（C15）**：`/leave/approvals`、`/grievances/approvals` 加状态 chips + 搜索 + pager（照抄 downloads chips 聚合模式）。
- **2c 考勤防重复（C13）**：`/attendance/save` 预检同班同日 sheet 存在 → flash 提示 + 跳转已有记录，不再静默新建；不加 DB 约束（避免存量清洗）。

## 批次 3：检索与效率

- **3a 全局搜索扩展（C4）**：search.py 增加资料下载（`_visibility_domain`）、校历活动、在线测验、LMS 课程、本人请假/申诉；每类角色过滤 + cap 10。
- **3b 收藏服务端化（C5）**：新模型 `edu.favorite`（user_id/card_key/sequence 唯一），首页常用区固定/排序读写服务端，localStorage 保留兜底；路由 `/my/favorites/save`（POST csrf）。
- **3c 课表打印视图**：`/student/timetable?print=1` 简化模板（去导航、@media print），页头「打印」按钮。
- **3d 小页**：`/quiz/my` 测验逐次成绩页（attempt 数据已有）；家长端孩子仪表盘补作业/打卡/周记摘要卡。

## 批次 4：治理与教师效率

- **4a 操作审计（C9，参考 Canvas Grade Change Log）**：新模型 `edu.audit.log`（user/action/model/res_id/desc/create_date + ilike 索引列），埋点：`/grading/save`、`/leave|grievances/set_state`、`/timetable/create|copy/run`、downloads 批量删除/移动；查询页 `/edu/audit`（privileged_staff，筛选+分页）。
- **4b 公告增强（C11）**：EduNotice + `date_until`（过期自动从列表/横幅/搜索 domain 消失）+ ir.attachment 附件（详情页展示下载）；正文 Text→Html（sanitize，迁移包裹 `<p>`，异常即回退仅做前两项）。
- **4c 教师作业管理（C12）**：发布后编辑（deadline/description）、撤回（active=False）、「提交名单」页（已交/未交，op.assignment.sub.line）。

## 第 5 批（2026-08-30 用户拍板"继续做"，A/B/C/D/F 已交付）

- ✅ A 通知偏好：edu.notify.pref + edu.message._notify_event（四事件接入），/my/notify
- ✅ B QR 限时自助签到：edu.attend.self.token 60s 轮换防代签，学生扫码置到堂
- ✅ C 成绩留痕增强：/grading/save 审计明细逐生 旧分→新分
- ✅ D 搜索快捷键：Ctrl/Cmd+K 或 / 聚焦顶栏搜索
- ⏸ E Office 转 PDF 预览：本地与生产容器均无 LibreOffice，需先加装 soffice 再实现（懒转换+ir.attachment 缓存方案已在调研中确定）
- ✅ F 学生导入：/edu/import/students 两段式（预览校验→确认写入，仅建档案不开账号）

## 原第 5 批（暂缓）清单（历史）

Excel 批量导入学生/成绩（两段式）；通知偏好矩阵（事件×渠道+TG）；QR 限时签到（轮换防代签）；成绩字段级 track 留痕；Ctrl+K 命令面板；Office 在线预览（LibreOffice 转码）。

## 验证闭环（每批）

`docker compose exec web odoo -c /etc/odoo/odoo.conf -d edu19 -u <模块> --stop-after-init` EXIT=0 → 各角色 curl 冒烟（含越权 303/404）→ `python3 scripts/check_english.py` 全绿 → 路径范围 commit。新表/新字段迁移一律 savepoint + information_schema 列检查（downloads v3 教训）。
