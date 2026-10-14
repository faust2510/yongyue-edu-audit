# 计划文档（docs/plans/）

**本页是本目录的总索引 —— AI 助手接手本仓时先读这一页**，再按「索引」定位该读哪几份；
每份计划的当前状态以**文档头部状态行**为单一来源，本页索引表只是它的镜像（门禁逐字比对两者）。

> **最后核对**：`2026-10-08` ｜ **份数**：`75`（`docs/plans/*.md`，**不含本页**；状态分布：已上线 30 / 归档 34 / 设计中 5 / 在研 6）
> 复核命令（原样可跑，2026-10-08 读数）：`ls docs/plans/*.md | wc -l` 得 **76**（含本页 ⇒ 75 份计划）｜`python3 scripts/check_docs_index.py` 得 **未登记 0｜重复登记 0｜索引不一致 0｜结论 OK**。
> ⚠ 「68 份」是 2026-09-26 的旧读数（见「已交付」第 50 行与 `docs/code-map.md` §8），**引用份数一律以本行为准**。

> **分工**：`docs/research/` = **外部先例**（别人怎么做的、能不能装、license 是否传染），入口见 `docs/research/README.md`；
> 本目录 = **本仓设计与交付留痕**（我们打算怎么做、做到哪一步、谁核过）。
> 铁律 0 要求「先调研后设计」：设计类文档必须引用其所依据的调研档案；外部先例结论写进 `docs/research/`，不写进本目录。

## 收录规范

1. **文件命名**：设计类 `<功能>-design.md`（例 `leave-approval-design.md`）；报告 / 评审 / 验证类 `<主题>-<种类>.md`（种类如 `implementation` `report` `review` `audit` `notes`）。**已被外部引用的旧名一律不改名**，走文末「有意不改名 / 保留原位」登记。
2. **每份文档头部必须有状态行**：位于正文**前 20 行内**，**有且仅有一行**，格式逐字如下（分隔符是全角 `｜`，左右各一个半角空格；四个值都用反引号包裹）：

   ```
   > **状态**：`已上线` ｜ **主题**：`请假审批` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
   ```

   少一个空格、把 `｜` 换成半角 `|`、漏掉反引号、主题超 24 字 —— 都算违规（门禁逐字校验）。
3. **状态只有四个值，语义固定**（别的写法一律非法）：
   - `设计中` —— 只有设计，零代码；
   - `在研` —— **本文范围内仍有未上生产的部分**（可能整篇未上，也可能只差一两项）；
   - `已上线` —— 已部署生产并验证；
   - `归档` —— 过程留痕，不再作依据（别再拿它当现状）。

   「代码写完」「升级 EXIT=0」「新进程能看到模型」都**不算**「已上线」—— 判据强度见 `docs/code-map.md` §10.1。
4. **主题 ≤ 24 字**：同一主题家族用**同一个**主题词（都写「请假审批」），家族指针靠它聚合；标题里的花活不要搬进主题。
5. **取代**：无取代写 `—`；有取代则写**本目录内一个真实文件名**（不是路径、不是标题），并在本文正文补一行横幅 `> ⚠️ 本文已被 [`新文件名`](新文件名) 取代`。取代链**不许成环**（门禁会打印环路径）。
6. **核对日期**（`YYYY-MM-DD`）= 最近一次**有人拿证据核对过**这份文档的日期，**不是成文日期**；核对用的命令 / 链接要能在正文追到。状态升级（`在研` → `已上线`）必须同时更新核对日期。
7. **单一来源 = 文档头部**：本页索引表镜像同样的值，门禁逐字校验两者一致；不一致时**以头部为准、改索引**，改完把门禁跑一遍。
8. **什么进哪里 + 登记义务**：本仓自己的设计与交付留痕进本目录，外部先例调研进 `docs/research/`。**新增计划文档必须同时登记进本页「索引」表**，否则 `python3 scripts/check_docs_index.py` 报红。

## 待办队列

> 本队列是全仓「该做什么 / 做到哪了」的唯一来源（原在 `docs/dev-workflow.md`，已于 2026-09-26 迁入本页）。

### 待办（按优先级）

| 序 | 功能 | 状态 | 设计文档 |
|---|------|------|----------|
| ① | **成绩中心（成绩簿）** —— 教务/教师双轴录入，一科一个总分；**已有实存实现（task-18，2026-10-03 交付）并在生产上运行**，2026-10-13 三轮访谈拍板 13 条，转为**追溯设计** | ✅ 2026-10-13 本轮收口完成并上生产（xlsx 往返 / 教务手工加人 / 后台「按科目」只读入口；本地 42/42 PASS、门禁全绿、DEPLOY_RC=0） | `docs/plans/gradebook-center-design.md` |
| ② | **排课链路改造**（先排课后报课 · 降本三件 · 教师不可用 · 人工排课路径）—— 该设计 §18「合班重排」已落地；**主体四件 2026-10-14 交付并上生产**（G1 报课池三档 / G2 覆盖看板 / G3 预检查三类化 / G4 教师不可用 + 自助登记） | ✅ 2026-10-14 已上生产（本地活体探针 52/52、静态门禁 9 张全绿、DEPLOY 通过、8 文件 md5 一致）；**运营待办：生产 `op.faculty` 只有 1 行且 `active=false`（占位「待定」）⇒ 教师不可用功能暂无载体，需先建真实教师档案** | `docs/plans/scheduling-overhaul-design.md` |
| ③ | **录取后发放入学码（C-3）**——「已录取 → 他能登录」；新模块 `edu_admit_invite`（只加 1 列 `edu.invite.code.application_id` + 2 个 object 按钮，**零新增路由/模型/表/ACL**） | ✅ 2026-10-14 已上生产（本地探针 54/54 PASS、门禁 7 张全绿、活体注册表 117/117 LIVE 0 DARK；首装须 `ACTION=-i`）；**生产暂无载体**：3 条申请全部 `state='new'`（按钮 invisible），且 `ir.mail_server` 仍 0 行 ⇒ 邮件只落 `state='exception'` | `docs/plans/admission-invite-link-design.md`（§18 任务书 + §18.5 实测 + §18.6 部署） |
| ④ | **评估收口第二步**：旧两套**只剩 A 套**（`edu.eval.*` in `edu_portal`）冻结 → 备份 → 删除 —— **B 套 `edu_eval` 已于 2026-09-29 卸载删模块**（`docs/audit/edu-eval-removal.md`：三张表均 0 行、授权原话在案），A 套仍在仓内且仍被引用 | 🟡 设计完成，A 套收口未做 | `docs/plans/evaluation-rebuild-design.md`（§7 旧两套处置） |
| ⑤ | **岗位两套合并**（一套实体 = `edu.job.posting` + 面向类型）—— 两套实体今仍并存：`edu.alumni.job` 仍被 `edu_public/controllers/main.py:215,225` 与 `edu_portal/controllers/roles.py:1553` 消费 | 🟡 设计完成，实现未开始 | `docs/plans/jobs-merge-design.md` |
| ⑥ | **`edu_dup_suspect`（疑似重复档案）搜索筛选器** —— 字段已建（`invite_code.py:732`，index=True），学生列表**只**有 `edu_pending_setup` 筛选器（`class_batch_views.xml:131-132`），`edu_dup_suspect` 的 filter 缺失（约 4 行 XML） | ✅ **已完成 2026-10-03**（筛选器已补进 `edu_portal/views/class_batch_views.xml:141`，与 `edu_pending_setup` 并列；实测域命中可红可绿：注入学生5 标记 → 命中 1 条，还原 → 0 条） | — |
| ⑦ | **课程中心排课入口**（`/my/study` 的课表 + 教务排课 + 「排课到人」）—— **P0（课程中心内嵌只读周课表）已于 2026-09-28 实施并在本地 `edu19` 自证**；**P1（教务排课面板 + 「排课到人」）与 P2（学生自助选时段，须新建模型）未开始**，仍阻塞在用户确认（设计 §10 A1/A2/A3/A7）；零新模型 | 🟡 P0 已实施（本地自证，未部署生产）；P1/P2 未开始（阻塞在用户确认） | `docs/plans/study-scheduling-design.md` |

### 已交付

| 序 | 功能 | 状态 | 设计文档 |
|---|------|------|----------|
| 1 | **排课系统**（周课表三视角 + 后台排课中心 + 并发兜底） | ✅ 已交付 2026-08-23 | `docs/plans/timetable-design.md` |
| 2 | **LMS 在线课程**（课程/课次/学习进度） | ✅ 已交付 2026-08-23 | `docs/plans/lms-design.md` |
| 3 | 财务缴费（账单/缴费记录门户） | ✅ 已交付 2026-08-23 | `docs/plans/fees-design.md` |
| 4 | 资产借还（设备/书籍借还） | ✅ 已交付 2026-08-23 | `docs/plans/assets-design.md` |
| 5 | 招聘后台（真实职位发布 + 简历收集） | ✅ 已交付 2026-08-23 | `docs/plans/jobs-design.md` |
| 6 | **在线报名与入学申请**（公开在线申请表 + 报名表元数据驱动引擎：管理员可视化增删字段与必填） | ✅ 已交付 2026-08-25 | — |
| 7 | 站内帮助中心（四角色公开指南）+ 门户自助改密码 + 教师工作台首页 | ✅ 已交付 2026-08-25 | — |
| 8 | edu_life 易用性改良（打卡 streak / 周记三态 / 评语引号面板）+ 报名表九区步骤感 + 评教匿名声明置顶 | ✅ 已交付 2026-08-25 | — |
| 9 | **资料下载中心**（教务上传 / 学生下载 / 分类管理 / 下载计数） | ✅ 已交付 2026-08-28 | `docs/plans/downloads-design.md` |
| 10 | 资料下载中心 v2（管理台 / 两级文件夹 / 批量操作 / 审计 / 上新提醒 / 可见范围四组勾选） | ✅ 已交付 2026-08-29 | `docs/plans/downloads-v2-design.md` |
| 11 | 钉钉式排课与应用板块体验改进（S1 冲突分色 / S2 周期排课 / S3 复制预览 / S4 周课表 / S5 校历三视图 / W1 常用区 / W2 编辑排序） | ✅ 已交付 2026-08-28 | `docs/plans/ux-improve-proposal.md` |
| 12 | 公开站死链导航接线（A9） | ✅ 已交付 2026-08-28 | `docs/plans/nav-fix.md` |
| 13 | 公告横幅（门户顶部横幅：字段 + 后台布告栏 + 前端轮播） | ✅ 已交付并生产验证 2026-08-29 | `docs/plans/notice-banner-deploy.md` |
| 14 | 全面去 Odoo 品牌化（favicon / 公司 logo 换校徽 / Powered by 与用户菜单外链清除 + 残留终扫六处） | ✅ 已交付 2026-08-29 | — |
| 15 | **辅助增强包 批次 1–4**（CSV 导出九连 / PDF·图片在线预览 / iCal 日历订阅 / 提醒补全 / 审批体验 / 考勤防重复 / 搜索扩组 / 收藏服务端化 / 课表打印 / 测验历史 / 家长摘要 / 操作审计 / 公告有效期与附件 / 教师作业管理） | ✅ 已交付 2026-08-30 | `docs/plans/aux-features-roadmap.md` |
| 16 | 辅助增强包 第 5 批（通知偏好 / QR 限时自助签到 / 成绩逐生留痕 / 搜索快捷键 / 学生 CSV 两段式导入） | ✅ 已交付 2026-08-30 | `docs/plans/aux-features-roadmap.md` |
| 17 | **学生自主报课与教务审批**（enroll-v2 第 2 期：全科目改选修 + 至少选 1 门校验） | ✅ 已交付 2026-09-06 | `docs/plans/enroll-v2-design.md` |
| 18 | **财务总账 + 报销**（双向台账 / 两段式报销 / 教务台账审批台；第三期） | ✅ 已交付 2026-09-10 | `docs/plans/ledger-design.md` |
| 19 | **v3 去 Odoo 化 + 学坊本土化 + 一条龙服务**（统筹费改写 / 币种按 `res.currency` / 术语收口 / 公开页英文清零） | ✅ 已交付 2026-09-12 | `docs/plans/ux-v3-delivery.md` |
| 20 | 学生一条龙服务 v3（会议链接 + 学习闭环） | ✅ 已交付 2026-09-12 | `docs/plans/study-hub-v3-design.md` |
| 21 | 资料闭环 v3（下载确认 + 未读名单 + 管理台下载） | ✅ 已交付 2026-09-12 | `docs/plans/downloads-ack-v3-design.md` |
| 22 | 重复劳动自动化（批量审批 / 成绩批量与留痕 / 公告模板与定时 / 考勤补录 / 学生自助） | ✅ 已交付 2026-09-12 | — |
| 23 | 公开页事实出处台账（Data Provenance：去幻觉 + 逐条来源） | ✅ 已交付 2026-09-12 | `docs/plans/data-provenance.md` |
| 24 | **全站无障碍收口**（axe 违规 738→0：色对比 / 表单可访问名 / 按钮·图片·链接名；门禁 BASELINE 收到 0） | ✅ 已交付 2026-09-14 | — |
| 25 | **配色统一 v4**（三层配色体系 + 唯一颜色令牌源 + 静态令牌门禁） | ✅ 已交付 2026-09-15 | `docs/plans/color-system-v4.md` |
| 26 | 课程清单幂等导入器（124 行 → 新建 115 科 / 新增挂接 306；复跑 0 新建 0 挂接） | ✅ 已交付 2026-09-14 | — |
| 27 | **生产数据订正**（币种 USD→CNY / 生产占位教师账号 / 接待转报销单） | ✅ 已交付并生产验证 2026-09-16 | `docs/plans/data-provenance.md`（§9） |
| 28 | 费用分类可配置化（校方自助增删分类 + 存量迁移） | ✅ 已交付 2026-09-16 | `docs/plans/fee-categories-design.md` |
| 29 | **权限分层**（「教务≠系统管理员」四层模型 + 后台可达性巡检 + 入口回补） | ✅ 已交付 2026-09-17 | `docs/plans/perm-model.md` |
| 30 | 后台菜单收口（admin 38→14 / backoffice→12 / faculty→9）+ 导航重复入口收口（3× 空页 /jobs → 0） | ✅ 已交付 2026-09-17 | — |
| 31 | **邀请码分层**（层级码 / 绑人码 / 多次码 / 批量生成 / 仅超管发教务码 + 家长层待分配档案） | ✅ 已交付 2026-09-17 | `docs/plans/invite-code-tiers-design.md` |
| 32 | **Telegram 发注册码机器人**（`edu_tg_bind`：一账号一张码 + inline keyboard） | ✅ 已交付 2026-09-17 | `docs/plans/tg-invite-bot-design.md` |
| 33 | **班级管理**：班级分配与回收站（需求 7） | ✅ 已交付 2026-09-18 | `docs/plans/class-batch-management-design.md` |
| 34 | **调班申请与教务审批**（学生申请 → 教务批；允许换课程） | ✅ 已交付 2026-09-18 | `docs/plans/class-change-request-design.md` |
| 35 | 改课影响面与变更通知（C-1） | ✅ 已交付 2026-09-18 | `docs/plans/session-change-impact-design.md` |
| 36 | 排课：各年级分开排（多班批量排课，时间自动错开）+ 旧合班课时批量停用 | ✅ 已交付 2026-09-18 | `docs/plans/scheduling-overhaul-design.md`（§18） |
| 37 | **评估系统重建第 1 期**（`edu_assess`：评分项行表 + 矩阵渲染 + xlsx 往返） | ✅ 已交付 2026-09-18 | `docs/plans/evaluation-rebuild-design.md` |
| 38 | 学生门户主页合并与头像统一（H-1） | ✅ 已交付 2026-09-18 | `docs/plans/student-portal-home-profile-design.md` |
| 39 | **课代表**（`edu.course.rep` + 课程内有限权限 + 请假审批留痕） | ✅ 已交付 2026-09-21 | `docs/plans/course-representative-design.md` |
| 40 | **专业编排（学制 + 必修/选修）**（关系表 + `subject_ids` 兼容层 + 334 行迁移 + 真删护栏） | ✅ 已交付 2026-09-22 | `docs/plans/major-track-elective-design.md` |
| 41 | **请假单拆分 + 分级审批 + 转交审批** | ✅ 已交付 2026-09-24 | `docs/plans/leave-split-approval-design.md` |
| 42 | 教职员工表单瘦身（22→8 字段，纯视图继承） | ✅ 已交付 2026-09-24 | `docs/plans/faculty-form-slim.md` |
| 43 | 层级码注册认领教务预建档案（防重复档案；命中失败留 `edu_dup_suspect` 信号） | ✅ 已交付 2026-09-24 | — |
| 44 | 密码逐字保存收口（注册 + 改密码，覆盖 core 的 strip）+ 系统通知可见可清未读 | ✅ 已交付 2026-09-24 | `docs/plans/password-verbatim-audit.md` |
| 45 | **中国直连入口** `cn.edu.example.org`（方案 A；中国访问从「多数超时」到 0.67s） | ✅ 已交付并生产验证 2026-09-24 | — |
| 46 | 站点探活 + Telegram 告警（每 5 分钟） | ✅ 已交付并生产验证 2026-09-24 | — |
| 47 | **前端瘦身**（lazy 包整族摘除 -420KB / 整族卸载未使用模块 6.66→6.23MB / 移除客服入口 →5.74MB；第四刀已探明不可行并回滚）+ 静态资源缓存与校徽瘦身 | ✅ 已交付 2026-09-24 | — |
| 48 | **门户入口合一与移动端适配**（财务入口合一 / 教务端课程编排门户入口 / 底栏不再被客服悬浮球压住 / 导航改指 `/my/password`） | ✅ 已交付 2026-09-24 | — |
| 49 | **文档收口**：`eval-merge-design.md` 补作废声明（头部 `取代` 指向 + 取代横幅，随本轮计划文档索引一并落地） | ✅ 已交付 2026-09-26 | `docs/plans/eval-merge-design.md` |
| 50 | **计划文档索引与防腐化门禁**：68 份计划文档逐份登记（主题/状态/取代/要点/判定依据；**68 = 2026-09-26 当日读数，现行份数见页首「最后核对」行**）+ 待办队列迁入 + 同一主题读哪份 + 头部机器可读状态行 + `scripts/check_docs_index.py`（五条不变式，已接进 code-map §10 提交闭环） | ✅ 已交付 2026-09-26 | `docs/plans/README.md` |

> **注**：本表日期 = **入库（commit）日期**，不等于生产生效日期。
> 生产生效要看**是否重启过 web 进程**（铁律见 `docs/code-map.md` §10.1）——例如
> **班级管理 09-18 入库、09-24 重启后才在活体进程加载**；各行的真实时线见下方索引表的「判定依据」列。

### 挂起/待定

| 序 | 功能 | 状态 | 设计文档 |
|---|------|------|----------|
| 1 | **6 名学生仍未分班**（泫 / 王院宇 / 张恩雨 / 裴枝 / 文文 / 24B0045）—— 待教务在班级管理里逐一挂班 | ⏸ 挂起（等教务操作；名单本身需校方核对，见下「无法确认」） | `docs/plans/class-batch-management-design.md`（「待分配」档案链路） |
| 2 | **A1/B1/B3/B4 四个年级班共 77 课时未归档**（A1 4 / B1 18 / B3 40 / B4 15）—— 与 9 个合班批的 139 课时共同构成生产 216 条 `op.session`；全套 `state='draft'`，未停用前**全部参与冲突检测** | ⏸ 挂起（处置方式需校方/教务拍板） | `docs/plans/scheduling-overhaul-design.md`（§18.5 映射表） |
| 3 | **邮箱通道**：报名邮件钩子已上线，但**外发 SMTP 凭据未配**（本机 `ir.mail_server` 实测 **0 行** ⇒ Odoo 退回 `localhost:25`，只能证到「邮件已生成」不能证「已送达」） | ⏸ 挂起（等校方提供 SMTP 凭据；推荐 QQ 邮箱授权码 `smtp.qq.com:465` SSL/TLS，另需配 SPF/DKIM） | `docs/plans/admission-invite-link-design.md`（§15 待确认 1/2/6） |
| 4 | Office 转 PDF 在线预览（辅助增强包第 5 批 E 项）—— 本地与生产容器均无 LibreOffice，需先装 soffice | ⏸ 挂起（等环境加装 soffice） | `docs/plans/aux-features-roadmap.md` |
| 5 | `op.program`（菜单 276「专业」）与 `op.course`（菜单 263）概念级重复 —— 本设计明确**只登记不合并**，需要唤醒条件（出现第二处给 `op.program` 写数据的入口，或教务开始用 276 建「专业」） | ⏸ 挂起（等唤醒条件／需校长拍板处置） | `docs/plans/major-track-elective-design.md`（§0 第 1 条） |

## 索引

> **登记行** = 表格行**首格是反引号包裹的文件名**（形如 `xxx-design.md`）。每份文档在本页**恰好登记一次**：
> 0 次 = 未登记、≥2 次 = 重复登记，两者都报红。因此「家族指针」「保留原位」等表格的首格**不要**写成反引号包裹的 `xxx.md`（会被计成第二次登记）。
> 列义：**要点** = 一句话结论（不是摘要）；**判定依据** = 凭什么算这个状态（命令 / 链接 / 证据）。

### 现行设计

| 文件 | 主题 | 状态 | 取代 | 要点 | 判定依据 |
|---|---|---|---|---|---|
| `timetable-design.md` | 排课系统 | 已上线 | — | 周课表三视角 + 后台排课中心 + 并发兜底已交付并上生产，是现行排课主干。 | `controllers/scheduling.py` + `views/scheduling.xml` + `/student/timetable` 路由在 HEAD；`code-map.md:313` 记「已交付」。 |
| `lms-design.md` | LMS 在线课程 | 已上线 | — | 课程 / 课次 / 学习进度三页已上线，是现行 LMS 设计。 | `edu.lesson` / `edu.lesson.progress` + `/my/courses` 在 HEAD（9ac86b9 入库、7b43a49 迭代）。 |
| `fees-design.md` | 财务缴费 | 已上线 | — | 账单 + 缴费记录门户已上线，管缴费前台（与总账/报销分工）。 | `fees.py:145/514` 定义 `edu.fee.bill`/`edu.fee.payment` + 9ac86b9 快照入库；自称「已交付（2026-08-23）」与事实一致。 |
| `assets-design.md` | 资产借还 | 已上线 | — | 设备 / 书籍借还已交付，模型 + 控制器 + 视图齐备。 | `models/assets.py` + `controllers/assets.py` + manifest `views/assets.xml`；`dev-workflow.md:1147` 记「✅ 已交付 2026-08-23」。 |
| `jobs-design.md` | 招聘后台与岗位发布 | 已上线 | — | 真实岗位发布 + 简历收集已上线；`jobs-merge-design.md` 是未实施的收口设计（见待办 ⑤），线上跑的仍是本文描述的 `edu.job.posting`，故取代填 —。 | `models/jobs.py` 的 `edu.job.posting`/`edu.job.application` + `edu_public` `/campus/jobs` 三路由存在；jobs-merge 未实施故不填取代。 |
| `ledger-design.md` | 财务总账与报销 | 已上线 | — | 双向台账 + 两段式报销 + 教务台账审批台已交付并生产部署。 | `fees.py` 有 `direction`/`reimburse_state`/`approved_amount` + f4e546e `feat(ledger)`；`code-map` 记「已交付并生产部署 2026-09-10」。 |
| `downloads-v2-design.md` | 资料下载 v2 管理台 | 已上线 | — | 管理台 / 两级文件夹 / 批量操作 / 审计 / 上新提醒 / 可见范围已上线，是下载中心现行设计出处。 | `edu.download.log`/`audience` 在 HEAD（`downloads.py:318`）+ 16d64c8 `feat`；`code-map.md:81` 仍以本文为下载中心设计出处。 |
| `downloads-ack-v3-design.md` | 资料下载闭环 | 已上线 | — | v3 闭环增量：下载确认 + 未读名单 + 过期下架，叠加在 v2 之上。 | 3b9f9c2 `feat(v3)`：`models/downloads.py:299` `edu.download.ack` + `downloads_views.xml:167` 过期下架 cron。 |
| `evaluation-rebuild-design.md` | 评估系统重建 | 在研 | — | 第 1 期（`edu_assess`）已上线；§7 旧两套**只剩 A 套**未收口（见待办 ④）。 | `edu_assess/models/assess.py` + 734ddd6 `feat` 第1期 + 生产 `ir_module_module=edu_assess installed`（`gradebook-entry.md:993`）；**B 套 `edu_eval` 已删**（`docs/audit/edu-eval-removal.md`，2026-09-29，三张表均 0 行），A 套 `edu.eval.template` 仍在 `edu_portal/models/evaluation.py:20`。 |
| `eval-materials-inventory.md` | 评估现状与素材盘点 | 设计中 | — | **6 份素材（`评估表格/`）全部读出 + 三套引擎逐 file:line 清点 + 缺口对照 + Excel 操作需求**；本轮零代码，7 条待用户拍板。 | 逐 `w:t` 覆盖断言缺失块 0/4 份；xlsx 公式/合并区实读；4 角色 × 14 路由实测（旧两套全 303）；`docs/plans/README.md` 待办 ④ 的输入件。 |
| `fee-categories-design.md` | 费用分类可配置化 | 已上线 | — | 校方自助增删费用分类 + 存量迁移已上线。 | `models/fees.py:52` 定义 `edu.fee.category` + 9a228da `feat`（含存量迁移）；本文:137 记生产已执行。 |
| `enroll-v2-design.md` | 学生自主报课 | 已上线 | — | 学生自主报课 + 教务审批（第 2 期全科目改选修）已上生产。 | `controllers/enroll.py` 有 `/subject/enroll` 等路由 + dd5cabc `feat` + f06721b 生产部署记录（生产 md5 一致）。 |
| `study-hub-v3-design.md` | 学生一条龙服务 v3 | 已上线 | — | 会议链接 + 学习闭环已上线；首页 IA 结论已被 `student-portal-home-profile-design.md` 修订（部分取代），故取代填 —。 | `edu.lesson.progress` + `/my/study` 路由存在 + 7b43a49 `feat` ⇒ 已上线；首页 IA 见 `student-portal-home-profile-design.md:67` 反向修订（部分取代）。 |
| `student-portal-home-profile-design.md` | 门户主页合并 | 已上线 | — | 学生/家长门户主页合并 + 头像统一（H-1）已上线，并反向修订了 study-hub-v3 的首页 IA（部分取代）。 | 6b47565 `feat` 交付 H-1：`batch2.py:1983` `/my/apps`→303 `/my/home`、`batch2.xml:1154` 头像弹窗接线。 |
| `color-system-v4.md` | 配色令牌 | 已上线 | — | 三层配色体系 + 唯一颜色令牌源已上线，是配色规范正本之一。 | `edu_brand/static/src/scss/brand_tokens.scss:155` 落地 `--border-control` 等令牌 + t3/t4 令牌接线提交（ee146fd、f0fdfae 等）。 |
| `color-tokens-t3.md` | 配色令牌 | 已上线 | — | t3 令牌采集与生成脚本产物在案，与 v4 同属配色规范。 | `brand_tokens.scss` + `scripts/color_tokens.py`/`json` 在案 + bb35f98 `feat(t3)` 交付物入库。 |
| `class-batch-management-design.md` | 班级管理与回收站 | 已上线 | — | 班级分配 + 回收站/恢复：**09-18 入库；09-24 09:52（01:52Z）重启后才在活体进程加载**；也是 6 名未分班学生的处置入口（见挂起 1）。 | `class_batch.py`（回收站/恢复按钮）+ `contacts.py` 同班同学在 HEAD + 5bf346d `feat`「班级分配与回收站（需求7）」（提交 09-18 15:55:25 +0800 = 07:55Z，正落在 §10.1 记的 09-18 05:13Z → 09-24 01:52Z 未重启窗口内）；生产只读复核 2026-09-26：`class_batch.py` 生产 sha1 == 本地，容器 `edu19-prod-web-1` 2026-09-24T14:29:16Z 启动后已加载。 |
| `class-change-request-design.md` | 调班申请与审批 | 已上线 | — | 学生申请 → 教务审批的换班链路（允许换课程）已上线，HEAD 冒烟 87/87。 | `/course/change/request` 在 HEAD（`batch3.py:372/478`）+ 9b8509d `feat`（提交 09-18 12:56:15 +0800，早于当晚 13:13 CST（05:13Z）那次 web 重启 17 分钟 ⇒ 与「该次重启即本次部署」相容）；HEAD 冒烟 87/87；生产只读复核 2026-09-26：`batch3.py`/`registration.py`/`batch3.xml` 生产 sha1 == 本地，容器 09-24 22:29 启动后已加载。 |
| `session-change-impact-design.md` | 改课影响面与变更通知 | 已上线 | — | 改课影响面计算 + 变更通知（C-1）已上线。 | `/timetable/session/<id>/impact` 在 HEAD（`main.py:891`）+ 5da2270 `feat`「（C-1）」。 |
| `gradebook-center-design.md` | 成绩中心（成绩簿） | 已上线 | — | 追溯设计：成绩中心已有实存实现（task-18，2026-10-03）并在生产上跑着；三轮访谈 13 条拍板 + 本轮三件收口（xlsx 往返 / 教务手工加人 / 后台「按科目」只读入口）。 | `624e748`+`5228ec8` 交付；本地活体 `tests/smoke/gradebook_center_io.py` 42/42 PASS；生产 11 个文件 md5 与本地逐一相同、`deploy_myedu.sh edu_portal` RC=0。 |
| `scheduling-overhaul-design.md` | 排课链路改造 | 已上线 | — | §18（各年级分开排 + 旧合班停用）由 `1ec787f` 交付；**主体四件（G1 报课池三档 / G2 覆盖看板 / G3 预检查三类化 / G4 教师不可用 + 自助登记）2026-10-14 由 `59c33a6` 交付并部署上生产**，实测见 §19.5。 | 本地活体探针 `tests/smoke/p1_scheduling_gate.py` 52/52 PASS（跑完自还原）；生产 `deploy_myedu.sh edu_portal,edu_schedule` 通过、8 个关键文件 md5 与本地逐一相同、四条新路由匿名 303 登录页（= 已进活体进程）。 |
| `enroll-timetable-link-repair-design.md` | 选课课表断链 | 设计中 | — | 只有设计、零代码：三条修法（甲=按 §18 排到年级班+停用旧合班课时 / 乙=教学班↔行政班归属 / 丙=最小止血）的取舍与本地干跑读数；**甲的操作单未在生产执行**。 | 本地 edu19 干跑 `tests/smoke/enroll_timetable_gap_dryrun.py`（B 段 6/6、C 段 13/13，残留自证=0）；「9 个合班批 139 节 / 挂批学生 0」由该探针 A 段逐条复跑。 |
| `admission-invite-link-design.md` | 录取后发放入学码 | 已上线 | — | 2026-10-14 交付并部署上生产（§18 任务书 + §18.5 实测 + §18.6 部署）：新模块 `edu_admit_invite` + 1 列 + 2 个按钮，**零新增路由/模型/表/ACL**；探针 54/54 PASS、门禁 7 张全绿。 | `tests/smoke/admit_invite_gate.py` 54/54（跑完自还原残留 0/0/0）；`ACTION=-i deploy_myedu.sh edu_admit_invite` 通过、活体注册表 117/117 LIVE、4 文件 md5 与本地一致、生产库列/唯一索引/视图各 1；`check_view_xpath` 常量 r19：34→36。 |
| `invite-code-tiers-design.md` | 邀请码分层 | 已上线 | — | 层级码 / 绑人码 / 多次码 / 批量生成已上线；原文自称「不写实现代码」与事实不符（已订正）。 | `invite_code.py` 有 `code_kind`/`tier`/`_guard_backoffice_tier` + e2739ce `feat`。 |
| `tg-invite-bot-design.md` | 注册码机器人 | 已上线 | — | Telegram 发注册码机器人（一账号一张码 + inline keyboard）已上生产。 | 【队长按生产实证改判】`tg_claim.py` 生产 md5 与本地一致（09-17）+ 活体注册表 91/91 LIVE。 |
| `course-representative-design.md` | 课代表权限 | 已上线 | — | 课代表（课程内有限权限 + 请假审批留痕）已上生产，与原文自称「只设计」冲突（已订正）。 | `models/course_rep.py:131` 定义 `edu.course.rep` + 149cab8 `feat`；`code-map.md:431` 记已上生产。 |
| `major-track-elective-design.md` | 专业编排（学制·必修选修） | 已上线 | — | 学制 + 必修/选修关系表与迁移已上生产；`op.program` 与 `op.course` 概念级重复只登记不合并（见挂起 5）。 | `models/major_track.py` 的 `edu.course.subject` + `op.course.edu_level_id` 存在 + d1a37f8 `feat`；生产 md5 一致。 |
| `leave-split-approval-design.md` | 请假拆分与分级审批 | 已上线 | — | 请假单拆分 + 分级审批 + 转交审批已上生产。 | 【队长按生产实证改判】`leave_flow.py`/`leave_transfer.py`/`roles.py` 生产 md5 与本地一致 + web 09-24 22:29 重启后已加载。 |
| `faculty-form-slim.md` | 教职员工表单瘦身 | 已上线 | — | 教职员工表单 22→8 字段（纯视图继承）已上生产。 | 【队长按生产实证改判】`faculty_form.xml` 生产 md5 与本地一致（09-24 11:16 落盘 < 22:29 重启）。 |
| `jobs-merge-design.md` | 岗位合并 | 设计中 | — | 岗位两套实体合并的收口设计，本轮明确只设计不实施，故设计中（待办 ⑤）。 | 【队长按生产实证改判】明确「本轮只设计不实施」；`audience` 字段 HEAD 0 命中、`/alumni/job*` 未 303 ⇒ 零代码。 |
| `ux-improve-proposal.md` | 排课与应用板块改进 | 已上线 | — | 钉钉式排课与应用板块体验改进（S1–S5 / W1–W2）已上生产。 | 【队长按生产实证改判】`session_ext.py` 生产 md5 与本地一致（09-18）且已加载；部署脚本模块清单含 `edu_schedule`。 |
| `aux-features-roadmap.md` | 辅助增强包路线图 | 在研 | — | 批次 1–4 + 第 5 批 A/B/C/D/F 已交付；仅 E（Office 转 PDF）因容器无 LibreOffice 暂缓，故在研。 | 155732d/5b76f63/6ffa9be/4481b67 `feat(aux1-4)` 全交付 + 第 5 批 A/B/C/D/F 已交付；E 项因容器无 LibreOffice 暂缓 ⇒ 未全量落地。 |
| `study-scheduling-design.md` | 课程中心排课入口 | 在研 | — | **P0（`/my/study` 内嵌只读周课表）已于 2026-09-28 实施并在本地 `edu19` 自证，未部署生产**（部署须用户确认）；**P1（课程中心内排课面板 + 「排课到人」写 `op.session.student_ids`）与 P2（学生自助选时段，须新建模型）未开始**，仍阻塞在设计 §10 的用户确认（A1/A2/A3/A7）。选 `在研` 而不是「已上线」：门禁语义 = 本文范围内仍有**未上生产**的部分（P1/P2 未做，且 P0 只在本地自证、未部署）。全程零新模型/零新字段/零新路由/零写路径；课表渲染仍复用既有 `/student/timetable`，周口径仍复用 `week_utils`。 | 【P0 实证】`tests/smoke/study_week_schedule.py` 50/50 PASS：四角色「本周课表」逐条 == SQL oracle == 既有 `/student/timetable`、区块内零 form/POST、整轮 `op_session`(288) 与 `op_session_op_student_rel`(0) 行数不变、三段夹具 `leftover=0`；改前反向证据留 `tests/smoke/out_study_week/before/`（区块命中 0）。同批：`ux_v3_route_matrix.py` 495 检查点全绿，`check_ui_surface.py`/`check_view_xpath.py`/`check_qweb_dict_foreach.py`/`check_live_registry.py`/`check_docs_index.py` EXIT=0。改动未提交（由队长提交）。⚠ 本行在 HEAD 里是**截断的 4 格行**（缺本列与行尾竖线），本次一并补齐。 |
| `2026-10-02-shared-ui-primitives.md` | 共享UI原件下沉 | 设计中 | — | 门户壳 `edu_page` 与窄屏卡片样式 `edu_narrow_table_cards` 住在依赖图**顶层**的 `edu_portal` 里，导致下层/旁层模块用不了：`edu_schedule` 因此有 2 处 `t-call` 引用了它**声明不到**的模板（manifest 在说谎，靠渲染期 xmlid 解析侥幸能用），另有 4 个页面的门户壳换不了。**初版「下沉到 edu_brand」已被前置核查证伪**（`theme_web_openeducat` 够不到 `openeducat_core`，照做等于把品牌模块绑上 ERP 核心）；修订方案＝**新建中间层 `edu_shell`**（dep: website + openeducat_core）装外壳，`edu_portal` 留同名别名（130+ 调用点一个不改）。**纯 CSS 的那一半已于同日实施**（`edu_narrow_table_cards` → `edu_brand`，commit `d2c3798`）；**要读模型的 `edu_page` 仍只设计不实施**。 | 实读 12 份 `__manifest__.py` 得依赖图；`grep -rc` 得调用点 24 文件（edu_page）/ 12 文件（卡片样式）；`find_wrong_shell.py` 实测 8 页；两次阻塞分别见 code-map §6 第 16 条与 `docs/audit/ui-visual-review/report.md` §5.2。 |
| `tg-assist-bot-design.md` | 行政班务机器人 | 在研 | — | 新建 `edu_tg_assist`（F1 定时提醒 / F2 一对一私发 `/dm` / F3 广播 `/notify` / F4 内联按钮回填 / F5 @提醒防漏 / F6 模板库 `/tpl`）， **刻意不碰**生产匿名意见箱 `edu_telegram`（硬边界 B1–B6：不读写 `edu.feedback.*` 与 `edu_telegram_outbox`、不占 `/telegram/webhook`、chat_id 与指纹永不 join）。 F1–F6 已在本地实现并逐条自证、**2026-10-08 已部署生产并完成接线**（复用 @sctrs_bot，经前门 `edu_tg_gate` 分发），**2026-10-09 用合成会话在生产端到端验过**（学生领码含幂等 / 老师指令与改道 / `/dm` 命中与找不到人 / 越权留痕 / `/notify` 短名 / F1 定时提醒的 ir.cron 生成·真实触发·自愈）；**仍缺**：BotFather 关隐私模式、拉群登记短名与人名（用户侧）、F5 三参数与 cron 46 未配 ⇒ 故仍在研；**F7（AI 提取 + Notion 归档）2026-10-10 已接通**（材料归档 + 规则/LLM 抽取 + 可选 Notion 导出；边界 B9–B12，默认零出网）；**2026-10-12 又接通三件**：①身份绑定码（`edu.tg.assist.bindcode` + `/bindcode` 出码 + 深链 `/start BIND-…` 一次绑定姓名与角色）②新手教程（学生版在 `edu_tg_bind` 领码回执里，教职工版 `help_text()` 按身份分版）③**学号登录**（网站 `/login` 支持「学号 + 密码」，邮箱不变，失败限速落库 `edu.portal.login.throttle`，见 §9.12）。 | 本地 `-u edu_tg_assist` EXIT=0、18 个模型全装载；odoo shell 实测 `_commands()` **7 条**（`/dm` `/help` `/name` `/notify` `/start` `/tpl` `/whoami`）； `tests/smoke/tg_assist_mention_probe.py` 22/22 且已接进门禁（`E2E tg_assist_mention` ✅）； 模板渲染 4 组对照（无 mention ⇒ `parse_mode=None` 且 payload 逐字节不变｜有 mention 且正文含该 @人名 ⇒ `parse_mode=HTML` + `tg://user?id=` 真提及｜有 mention 但正文无该人名 ⇒ 仍 `None`｜`& < >` 转义）； 生产 14 个模块含 `edu_tg_gate`，活体注册表 102/102 模型 LIVE、0 DARK。 |
| `eval-unified-design.md` | 评估统一引擎 | 在研 | — | **以 C 套 `edu.assess.*` 为基座统一三套评估**：给出「自定义创建」边界表（35 项逐条裁决：可自定义/固定/只读）、6 组硬缺口解法（**零新模型，12 个新增字段**）、9 条「像 Excel」逐条结论（**冻结表头与 Excel 整块粘贴给出具体实现路径**）、权限口径、迁移口径（**不动用户已有数据**）。**第 2 期已在工作区落地（本地自证）、尚未部署生产** ⇒ 状态由 `设计中` 升为 `在研`（本仓语义：本文范围内仍有未上生产的部分）；两处「设计承诺 vs 实现」偏离已就地登记（§5.3 模板级开关 → 模块常量 `ALLOW_PARTIAL_DUAL`、§5.7 停用位 → 只有硬护栏）。 | 【本地自证 · 未部署】`custom_addons/edu_assess/models/assess.py` 507 → **1517 行**（`wc -l`）；§3.3 的 12 个字段全部落地（`weight_mode`/`excellent_enabled`/`scale_anchors`/`scale_rule`/`parent_id`/`item_kind`/`track`/`score_mode`/`summary`/`objective_scorer_kind`/`subjective_scorer_kind`/`score.track`）+ 唯一键追加 `track`；`tests/smoke/assess_engine_v2_results.json` **items=74 / pass=74 / fail=0**；生产无实证（未部署）⇒ 不满足 `已上线`（= 已部署生产并验证）。 |

### 交付与实施报告

| 文件 | 主题 | 状态 | 取代 | 要点 | 判定依据 |
|---|---|---|---|---|---|
| `2026-08-25-downloads-implementation.md` | 资料下载 v1 实施 | 归档 | downloads-v2-design.md | ⚠️ **已取代，见 `downloads-v2-design.md`**。下载中心 v1 实施留痕，作 v1 前序证据。 | `downloads.py:14/59` 定义 `edu.download.category/file` + f915056 `feat`；v2（16d64c8/0a98d34 单页两态）后扩展 ⇒ 指向 v2 设计。 |
| `ux-implement-report.md` | 门户体验改进 t4 | 归档 | — | t4 实施说明；所述改动已由 ux-rework 交付，本文只作过程留痕。 | 文件名 + 首段 = 「t4 实施说明」（报告类）；所述改动确已由 727a6f9 `feat(ux-rework)` 交付。 |
| `ux-rework-handoff.md` | 钉钉式排课改造交付 | 归档 | — | 钉钉式排课改造交付报告（S1–S5 / W1–W2 七项落地）。 | 交付报告类；727a6f9 `feat(ux-rework)` 七项落地（S1-S5/W1-W2）。 |
| `ux-v3-delivery.md` | v3 改造交付 | 归档 | — | v3（去 Odoo + 学坊本土化 + 一条龙）交付总结，2026-09-14 **已上生产（交付事实）**；本文 `归档`，不再作依据。 | 交付报告类（M1–M10 + t9 验证 + 四条评审链）；生产部署已于 2026-09-14 完成（§5 4a）。 |
| `leave-split-approval-s3-report.md` | 请假分级审批 | 归档 | — | 请假分级审批 S3 过程报告；原文写「未 commit」与实际不符（已订正）。 | `leave_flow.py` + `leave_transfer.py` 存在 + 2fe14e9 `feat`（文档原写「未 commit」⇒订正）。 |
| `leave-split-approval-s5-report.md` | 请假审批门禁 | 归档 | — | S5 门禁报告：冒烟 46 PASS；原文写「未 commit」与实际不符（已订正）。 | `tests/smoke/leave_split_approval.py` 存在（46 PASS）+ 2fe14e9 提交。 |
| `batch4-cleanup-notes.md` | batch4 清理遗留 | 归档 | — | batch4 批次的遗留观察笔记，纯归档。 | 提交说明即「…遗留观察笔记归档」（7d381f1）。 |
| `batch4-p2-a1-approval-aggregation.md` | 审批待办聚合 | 归档 | — | A1 审批待办聚合的实施留痕（E2E 27/27 + 回归）。 | §2 E2E 27/27 + §2.1 回归；57c9dab `feat`，`/grievances/approvals` 在 HEAD。 |
| `notice-banner-deploy.md` | 公告横幅 | 已上线 | — | 门户顶部公告横幅已上线，生产探活全 200。 | `notice.py:43` `banner_enabled` + `/my/notice_banner` + 4515f16/bce5ec8 实测存在，文档载明生产部署探活全 200。 |
| `agent-health-audit-t2-unblock-log.md` | 团队解卡操作日志 | 归档 | agent-health-audit-final-report.md | ⚠️ **已取代，见 `agent-health-audit-final-report.md`**。t2 解卡操作日志，结论由更晚的 final-report 收口。 | 操作日志/存档类（76b06b4）；同主题更晚文档 `agent-health-audit-final-report.md`（e09bd93）已收口结论。 |
| `google-fonts-localization-report.md` | Google 字体本地化 | 已上线 | — | 前端资产包第 1 行的阻塞式 Google 字体 @import 已换成 /web/content 本地字体；2026-09-28 已在生产上线（生产自己的附件 id 1317、served bundle 9915b9e、googleapis 与 gstatic 命中 0、54/54 woff2 全 200、未重启 web）；屏蔽 Google 时 DCL 由 3/3 超时变 3/3 到达 0.12–0.30s 且对外 0 请求。 | §1.3/§5 黑洞对照 + §5.1 四份 usability 读数（A 轴 0）；§6.1 隔离克隆 `-u website` 持久性实测；§6.2 官方逆操作回滚实测；§10 生产实测（出网闸门两域名 200/200、`google-font%` 0→54+1、`orm_signaling_assets` 3→4、`check_live_registry` 91/91 LIVE 0 DARK、回归全 200）。 |

### 评审与验证

| 文件 | 主题 | 状态 | 取代 | 要点 | 判定依据 |
|---|---|---|---|---|---|
| `ux-v3-verification.md` | v3 改造验证 | 归档 | — | v3 的 t9 独立验证报告，是 ux-v3-delivery 的引证来源。 | 首段即 t9「独立验证报告」；其 §12/§17/§28 被 `ux-v3-delivery.md` 引为证据。 |
| `ux-v3-review-t4.md` | Odoo 痕迹清零评审 | 归档 | — | t4 评审判 needs_revision；其 F1–F5 已由 t31/t44 处理并经 t45 复评 pass 闭环。 | 评审报告类（verdict=needs_revision，6e8b6b5）；F1–F5 经 t31/t44 处理 + t45 复评 pass 闭环。 |
| `local-regression.md` | 排课回归 | 归档 | — | ux-rework t6 的排课本地回归报告，仅被引用未被取代。 | 首段「本地回归报告」（ux-rework t6，2026-08-28）；后续仅被引用未被取代。 |
| `portal-regression-readings.md` | 门户回归读数 | 归档 | — | 门户回归读数档：101 条断言全绿、exit 0。 | 首段「回归读数」档（101 条断言全绿 exit 0）；无更晚同主题文档。 |
| `perm-split-verification.md` | 权限分层验证 | 归档 | — | t4 verifier 的权限分层独立验证；与 audit 为同批不同角色留存。 | 首段「独立验证报告」（t4 verifier）；与 `perm-split-audit.md` 为同批不同角色留存。 |
| `review-t5-i18n.md` | 学坊本土化评审 | 归档 | — | t5 学坊本土化评审 verdict=pass，被 ux-v3-delivery 引为验收依据。 | 评审报告类（verdict=pass 快照，随 3b9f9c2 入库）；结论被 `ux-v3-delivery.md:430` 引为验收依据。 |
| `t12-review-t6-onestop-service.md` | 一条龙服务评审 | 归档 | — | t12 对一条龙服务的评审 verdict=pass；相关集成提交 d345413。 | 首段「t12 评审报告…verdict=pass」；相关集成提交 d345413。 |
| `t13-review-t7.md` | 成绩留痕评审 | 归档 | t35-review-t7-round2.md | ⚠️ **已取代，见 `t35-review-t7-round2.md`**。成绩留痕 t13 评审，结论由 t35 复评核验。 | 评审报告类；`t35-review-t7-round2.md` 首段即「t13 findings 的修复核验」且 verdict=pass ⇒ 填取代。 |
| `t32-review-t31.md` | 邮件去 Odoo 复评 | 归档 | t45-review-round3.md | ⚠️ **已取代，见 `t45-review-round3.md`**。t32 复评的 F1/F2 已治根；该主题最新一轮是 t45。 | 复评报告类；F1/F2 已由 t44 治根、t45 自述「均已治根」⇒ 填取代。 |
| `t35-review-t7-round2.md` | t7 复评核验 | 归档 | — | t35 对 t13 findings 的复评核验 verdict=pass，是该主题最新一轮。 | 复评报告（verdict=pass）；`t13-review-t7.md` 的后继（后者已标「已被 t35 取代」）。 |
| `t45-review-round3.md` | 邮件去 Odoo 复评 | 归档 | — | 邮件去 Odoo 的第三轮复评 verdict=pass，为该主题最新。 | 评审报告类；为 `t32-review-t31.md` → 本文的最新一轮（t45 verdict=pass）。 |
| `t92-smoke-family-readings.md` | 门禁冒烟读数 | 归档 | — | 门禁/冒烟读数定稿（含 t106 收口），被 ux-v3-delivery 引为最终家族读数。 | 门禁/冒烟读数定稿（含 t106 收口）；被 `ux-v3-delivery.md:345` 引为最终家族读数。 |
| `v2.1-regression.md` | v2.1 全量回归 | 归档 | — | v2.1 批次上线前门禁依据（全量回归报告）。 | 首段「上线前门禁依据」；v2.1 批次 ebc5cff 已入账「生产已部署」。 |
| `v2-checklist.md` | v2 改造清单 | 已上线 | — | v2.1–2.4 已上线；原写「待用户最终确认后动工」与事实不符（已订正）。 | 正文 :98/:109/:119 载 v2.1–2.4 已上线 + ebc5cff「生产已部署」⇒订正。 |
| `batch4-p2-regression.md` | 批次4 P2 回归 | 归档 | — | 批次 4 P2 交付前总回归 + 验收材料。 | 首段自述「交付前总回归 + 验收材料」；对应 ad9508d `docs(batch4-p2)`。 |

### 审计与台账

| 文件 | 主题 | 状态 | 取代 | 要点 | 判定依据 |
|---|---|---|---|---|---|
| `perm-split-audit.md` | 权限分层收口巡检 | 归档 | — | 权限分层收口巡检报告；发现的问题修复链已交付。 | 巡检/审计报告类；`tests/smoke/backoffice_reachability.py` 存在 + 2773ffe/3ef6cba/589178b 修复链已交付。 |
| `password-verbatim-audit.md` | 改密码逐字保存 | 归档 | — | 改密码逐字保存审计；处置已落地（含注册链路）。 | 审计类；`models/res_users_password.py` 存在 + 94ae034 `fix`。 |
| `batch4-p2-w3-badge-audit.md` | 角标 0 值审计 | 归档 | — | 角标 0 值审计留痕；修复已落地。 | 首段即「审计项」留痕类；其修复已落地于 4608e7b。 |
| `agent-health-audit-final-report.md` | AgentTeams 健康审计 | 归档 | — | AgentTeams 健康审计收尾报告，无代码交付物。 | 审计收尾报告类（e09bd93 + 85dd499）；无代码交付物。 |
| `i18n-verification-ledger.md` | i18n 汉化验证判据 | 归档 | — | 汉化验证的判据与证据索引，是判据清单而非现状依据。 | 首段自述「判据与证据索引」；其引用的 `check_odoo_trace.py`、`check_english.py` 均在案。 |
| `data-provenance.md` | 公开页事实出处 | 已上线 | — | 公开页事实出处台账（去幻觉 + 逐条来源），随生产订正同步，属活引用台账。 | 所覆盖的 `edu_brand` 公开页已上线；60eb892 生产币种 USD→CNY 同步 §9。 |

### 参考资料

| 文件 | 主题 | 状态 | 取代 | 要点 | 判定依据 |
|---|---|---|---|---|---|
| `ui-reference.md` | 工作台 UI 规范 | 已上线 | — | 工作台 UI 定稿规范，配色/控件先读这份。 | `edu_brand/static/src/css/backend_b11.css` + `ux_v3.css`/`brand_tokens.scss` 令牌；ebc5cff 记 v2.1/v2.2 批次「生产已部署」。 |
| `perm-model.md` | 权限四层规范 | 已上线 | — | 「教务≠系统管理员」四层权限模型规范，权限家族正本。 | `views/group_tuning.xml` 存在 + d2c41de `feat(perm)` 四层落地 + `code-map` §6.12 硬约定。 |
| `oss-research.md` | 开源排课调研 | 归档 | — | 开源排课调研（License 边界结论），属历史调研保留原位。 | 调研报告类；`code-map.md:346`「License 边界结论；完成」。 |
| `ux-research-dingtalk.md` | 钉钉交互模式调研 | 归档 | — | 钉钉/企微/飞书交互模式调研，结论被 ux-improve-proposal 引用。 | 外部产品交互模式调研报告；结论被 `ux-improve-proposal.md` 引用。 |

### 归档

| 文件 | 主题 | 状态 | 取代 | 要点 | 判定依据 |
|---|---|---|---|---|---|
| `downloads-design.md` | 资料下载 | 归档 | downloads-v2-design.md | ⚠️ **已取代，见 `downloads-v2-design.md`**。v1 下载中心设计；原文自称「等待实施」与事实不符（已订正）。 | `downloads.py` 定义 `edu.download.category/file` + f915056 `feat`；v2 自述其为 v1 前序 ⇒ 填取代。 |
| `eval-design.md` | 评估中心 v2-P2 | 归档 | evaluation-rebuild-design.md | ⚠️ **已取代，见 `evaluation-rebuild-design.md`**。A 套评估（`edu.eval.*`）**当年已上生产（交付事实）**；该设计已于 2026-10-06 归 `归档`，不再作依据。旧两套**只剩 A 套**待收口（B 套 `edu_eval` 已于 2026-09-29 删除，见待办 ④）。 | `evaluation.py:20/66/123` 定义 `edu.eval.template/task/score` + 74c1c99 同提交交付；A 套 `/my/evaluation` 已被 `eval_compat.py` 303 重定向。 |
| `eval-merge-design.md` | 评估引擎合并 | 归档 | evaluation-rebuild-design.md | ⚠️ **已取代，见 `evaluation-rebuild-design.md`**。评估引擎合并设计已作废（零代码）；重建设计明写作废它。 | `edu.eval.campaign` 全仓 0 命中；`evaluation-rebuild-design.md:29`「本设计作废 eval-merge-design.md」。 |
| `nav-fix.md` | 公开站死链导航 | 归档 | — | 公开站死链导航修复已结案，生产 0 死链。 | 「说明与验证」+「✅ 已结案」；`scripts/nav_fix.py` 已跑生产（code-map：0 死链）。 |

## 同一主题读哪份（家族指针）

> 同一主题常有「设计 → 实施 → 评审 → 归档」多份；此表只回答「只想读一份时读哪份」。
>
> ⚠ **本表「份数」= 2026-10-06 实测**，口径 = `docs/plans/*.md` 中属于该主题家族的**全部**文档（**含已归档 / 已取代的过程文档**）；每行「=」后已逐份列出组成 ⇒ 数字可当场复核。
> **索引总量不在这里**：以页首「最后核对」行为准（本表各行之和 ≠ 总量，74 份里多数不属于任何多文档家族）。

| 家族 | 份数 | 先读哪份 |
|---|---|---|
| 资料下载 | 4 | [downloads-v2-design.md](downloads-v2-design.md)（现行；v3 是增量回执，v1 两份已标取代）。4 = downloads-v2-design + downloads-ack-v3-design + downloads-design（已标取代）+ 2026-08-25-downloads-implementation（已标取代） |
| 评估 | 5 | [evaluation-rebuild-design.md](evaluation-rebuild-design.md)（设计）；**先读现状请走 [eval-materials-inventory.md](eval-materials-inventory.md)**（素材提取 + 三套清点 + 缺口对照）。5 = 上述两份 + [eval-design.md](eval-design.md)（A 套原设计，已标取代）+ [eval-merge-design.md](eval-merge-design.md)（已作废）+ [eval-unified-design.md](eval-unified-design.md)（统一引擎，在研） |
| 请假 | 3 | [leave-split-approval-design.md](leave-split-approval-design.md)（两份 report 是过程证据）。3 = 该设计 + leave-split-approval-s3-report + leave-split-approval-s5-report |
| UX v3 | 6 | [ux-v3-delivery.md](ux-v3-delivery.md)（结论）+ [ux-v3-verification.md](ux-v3-verification.md)（独立验证）。6 = 交付/验证三份（ux-v3-delivery / ux-v3-verification / ux-v3-review-t4）+ 同批评审与读数三份（review-t5-i18n / t12-review-t6-onestop-service / t92-smoke-family-readings） |
| 权限 | 3 | [perm-model.md](perm-model.md)（规范；另两份是巡检/验证留痕）。3 = perm-model + perm-split-audit + perm-split-verification |
| 配色 | 3 | [ui-reference.md](ui-reference.md)（定稿规范）。3 = ui-reference + color-system-v4 + color-tokens-t3 |
| 班级与课次 | 3 | 按功能各自读，三者互为交叉引用。3 = class-batch-management-design + class-change-request-design + course-representative-design |
| 排课 | 8 | 现行主干 [timetable-design.md](timetable-design.md)（已上线）；待办 ② 主体读 [scheduling-overhaul-design.md](scheduling-overhaul-design.md)；课程中心入口读 [study-scheduling-design.md](study-scheduling-design.md)。8 = 上述三份 + [session-change-impact-design.md](session-change-impact-design.md)（改课通知）+ [enroll-timetable-link-repair-design.md](enroll-timetable-link-repair-design.md)（断链止血）+ 过程报告 3 份 [ux-improve-proposal.md](ux-improve-proposal.md) / [ux-rework-handoff.md](ux-rework-handoff.md) / [local-regression.md](local-regression.md) |
| batch4 批次 | 4 | [batch4-p2-regression.md](batch4-p2-regression.md)（总回归）即可；其余为历史批次留痕。4 = batch4-p2-regression + batch4-p2-a1-approval-aggregation + batch4-p2-w3-badge-audit + batch4-cleanup-notes |
| 团队/汉化审计 | 3 | 前两者读 [agent-health-audit-final-report.md](agent-health-audit-final-report.md)（t2 日志已标取代）；后者 [i18n-verification-ledger.md](i18n-verification-ledger.md) 独立。3 = agent-health-audit-final-report + agent-health-audit-t2-unblock-log + i18n-verification-ledger |

## 有意不改名 / 保留原位

本目录有大量外部引用（`grep -ro 'docs/plans/' . | grep -v '^\./docs/plans/' | wc -l`，2026-09-26 读数 898 处 —— **这是带日期的历史读数，随改动漂移；引用前重跑该命令**；其中 `custom_addons/` 内 **123 处、覆盖 59 个 `.py/.xml/.js` 源文件** —— 源码注释里直接写着文档路径，**改名 = 一次制造上百条死链**，故本目录**一律不搬家、不改名**）：命名不合规范的在这里登记；历史文档靠头部的「取代」字段收敛指向，而不是靠改名。
（同理 `docs/research/README.md` 也把两份早期文档登记为「保留原位」。）

> 登记注意：本表首格**不要**写成反引号包裹的 `xxx.md`（门禁会把它计成第二次登记）—— 写文件名本身，或写成 Markdown 链接。

| 文件 | 保留原因 |
|---|---|
| [2026-08-25-downloads-implementation.md](2026-08-25-downloads-implementation.md) | 命名用**日期前缀**旧体例；改名会破外部引用之一/若干，收益不足 |
| [color-system-v4.md](color-system-v4.md) | 命名用**版本号**体例；改名会破外部引用之一/若干，收益不足 |
| [color-tokens-t3.md](color-tokens-t3.md) | 命名用**版本号**体例；改名会破外部引用之一/若干，收益不足 |
| [v2-checklist.md](v2-checklist.md) | 命名用**批次号**体例；改名会破外部引用之一/若干，收益不足 |
| [v2.1-regression.md](v2.1-regression.md) | 命名用**批次号**体例；改名会破外部引用之一/若干，收益不足 |
| [t12-review-t6-onestop-service.md](t12-review-t6-onestop-service.md) | 命名用**任务号**体例；改名会破外部引用之一/若干，收益不足 |
| [t13-review-t7.md](t13-review-t7.md) | 命名用**任务号**体例；改名会破外部引用之一/若干，收益不足 |
| [t32-review-t31.md](t32-review-t31.md) | 命名用**任务号**体例；改名会破外部引用之一/若干，收益不足 |
| [t35-review-t7-round2.md](t35-review-t7-round2.md) | 命名用**任务号**体例；改名会破外部引用之一/若干，收益不足 |
| [t45-review-round3.md](t45-review-round3.md) | 命名用**任务号**体例；改名会破外部引用之一/若干，收益不足 |
| [t92-smoke-family-readings.md](t92-smoke-family-readings.md) | 命名用**任务号**体例；改名会破外部引用之一/若干，收益不足 |
| [ux-research-dingtalk.md](ux-research-dingtalk.md) | 调研类，且被 `docs/research/README.md` 登记为「历史调研保留原位」；改名会破外部引用之一/若干，收益不足 |
| [oss-research.md](oss-research.md) | 调研类（`docs/research/README.md` 未登记它，见该页「历史调研」段只列了 peer-research 与 ux-research-dingtalk）；改名会破外部引用之一/若干，收益不足 |

---

> **防腐化门禁**：`python3 scripts/check_docs_index.py`（五条不变式；退出码 0=OK 1=FAIL 2=ENV 3=INCOMPLETE）；
> `--selftest` 内置反例 9 个 / 正例 4 个自证判据有效（另有 10 类违规逐一命中 + 一条「夹具与真实文件逐字同形」对照断言）；`--coverage` 打印登记率、最长取代链、例外登记条数。
> 门禁零环境依赖（不连 DB、不发 HTTP、不读容器，停机可跑）。
