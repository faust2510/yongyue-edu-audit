# 全站交互对齐审计 · 缺口总清单（2026-08-23）

> **执行状态更新（同日晚）**：
> - **A 快修包 6 项全部完成并回归通过**（A1 铃铛路径 / A2 媒体队列入口 / A3 Fees+会议+Zoom 三卡上首页 / A4 登录页演示按钮 5/5 / A5 页脚社交 303→平台主页〔字段在 website 对象〕/ A6 归入 D1 未动）
> - **D2 方向落地：邀请码注册系统已上线**——`edu.invite.code` 模型 + 后台"邀请码"菜单（仅系统组）+ `/web/register` 注册页 + 登录页入口；原生 signup 保持禁用。E2E 四分支全过：无效码拒/过期码拒/有效码自动登录进门户/码复用与邮箱冲突拒绝。
> - B/C 包与 D1/D3/D4/D5 维持未执行，待后续拍板。

---

> - 验收：/event /blog /campus/jobs /jobs /alumni /online-exams /courses-offered 七页 200 且品牌关键词全命中。

---

# 清理+图标+权限裁剪+行政系统轮（2026-08-23 深夜，用户四连需求）

## ① 幻觉清理
- 页脚电话 +1 555-555-5556 删除（品牌手册红线：仅邮箱）
- 图书馆 29 本真实出版物全部下架（含 29 册单元、25 孤儿作者、9 出版社）；seed_yongyue_data.py 书单段摘除防复发
- ⚠️ 留痕：种子注释称书目出自《永约学坊2026招生简章》——若确属校方书单，重跑该脚本可恢复
- 学生档案占位地址等官方残留待后续逐页清扫（本轮先清用户点名的电话/书籍）

## ② 首页图标美化
24+ 张卡从企业版灰阶 SVG 换为 Font Awesome 彩色瓦片（每卡语义图标+专属底色，品牌紫/金点缀），视觉模型验收"清晰可辨、色彩区分、无裂图"。FA_HOME_ICONS 映射表集中在 batch2.py 便于调整。

## ③ 教师端应用裁剪（三态验证全过）
- 新组「后台·完整视图」(edu_portal.group_backend_full)：11 个非教学根菜单**整棵子树** group_ids 替换为仅该组
- 教师登录 → 仅见 时间表/课堂考勤/作业/考试/图书馆/测验/学生/SIS/教务审批 等教学应用（0 泄漏）
- 超管/教务 → 全开（system 隐含 + backoffice 直加）
- **开关机制**：设置→用户→勾选「后台·完整视图」即单独放开某人
- ⚠️ 调试血泪：Odoo19 的 search() 不再过滤菜单需显式 _filter_visible_menus()；搜索视图 group 的 expand/string 属性被移除；groups_id→group_ids；**角色系统会把新组经"角色/管理员"隐含回传给教师**（守卫已固化进 seed_teacher_menus.py）

## ④ 行政管理系统（新增，此前从未开发）
| 功能 | 实现 |
|---|---|
| 学生自助打卡 | edu.daily.checkin（到堂/灵修/读经 三开关+读经范围+备注，unique(学生,日期)），页内 30 天记录+本月到堂/连续灵修/连续读经统计 |
| 教师给学生加减分 | /my/points：学生下拉+快捷原因按钮(±分值)+自定义原因；流水列表 |
| 管理员给教师加减分 | 后端「日常管理→积分流水」list/form（person_kind 切换学生/教师）；教师排行 graph 视图 |
| 学生查看 | /my/points/me 合计+个人流水 |
回归：打卡保存/历史统计 ✓、自定义与快捷两种发放 ✓、落账与流水可见 ✓、越权归属校验齐全。

## 已知边界
- Placement offer 的后台录入入口未做（页面空态兼容）
- 测验徽章紫色已恢复；D2/D4 前轮已完成

---

# 执行轮（2026-08-23 深夜，6 子代理并行 + 主代理集成）——全部完成

> **补漏轮（同日，用户追问后自查发现漏派）**：
> - **B5** 数字图书馆：游客 303 根因=分类卡写死链到 auth='user' 的 /library/media；已改公开页内 ?type= 过滤 + 新增 /digital-library/material/<id> 详情页（游客全程可浏览）。回归：列表/过滤/详情/越界回退全过。
> - **B7** 档案动作五件套：edu.student.skill 与 edu.placement.offer 两个新模型 + 五条路由（技能添加/Offer加入拒绝/请假撤回[置refused留痕]/费用PDF下载[双报表兜底+越权兜底]/道歉表复用grievance）。回归 5/5 PASS（含造数 offer/leave 实测）。
> - 至此 **B 包 10/10、D1/D2/D3/D5 全部闭环**。剩余未做仅 C 包造数据（未点单）与 D4 即时聊天卡（待用户决定接 livechat 或移除）。
>
> **C/D4 收尾轮（同日，用户拍板：D4 接入 + C 按"永约学坊"品牌造数 + 测验徽章恢复紫色）**：
> - **D4 livechat 接入**：im_livechat.channel「校园服务」（坐席=faculty+admin），首页即时聊天卡动态指向 /im_livechat/support/<id>（无频道时回退 #）。完全免费，纯容器内模块。
> - **③ 测验徽章**：a.oe_count 徽章恢复品牌紫 #714B67（CSS 已入包）。
> - **C 包 7 页全部有内容**（scripts/seed_c_content.py 幂等种子）：3 场活动（开学说明会/小要理读书会/宗教改革讲座）、永约学坊文集 3 篇短文、3 条职位、3 位演示校友挂 CRS-PRP 结业、op.exam 兜底 1 条；品牌红线=联系方式仅 scrtsschool@gmail.com，无拟真人名。
> - 验收：/event /blog /campus/jobs /jobs /alumni /online-exams /courses-offered 七页 200 且品牌关键词全命中。

用户拍板：B 包必做（功能优先、内容不抄原版）、D1 完整接线、D3 按分类已读语义实现、D5 解隐可用卡保留缺失卡隐藏。
分工纪律：按文件所有权切分六个代理并行编码（禁碰容器），主代理统一升级联调。

## 交付明细
| 项 | 内容 | 代理 |
|---|---|---|
| B1 | /student/progression 进展页（出勤率/作业提交率/测验均分聚合+进度条+空态） | Y |
| B3 | /student/exam/data/<id> 考试详情页（三态成绩行） | X |
| B6 | 测验结果下钻（列表徽章→最近结果页；总览行"查看详情"）；顺手修了结果页越权漏洞 | Z |
| B8 | /courses?course=N 课程详情视图（无效参数回退列表） | W |
| B9 | /grade-book/report/download 成绩 CSV（BOM 防 Excel 乱码） | Y |
| B10 | 家长端两处「为孩子请假」入口 | V |
| B4 | 布告栏 notice/circular 双 tab | Y |
| B2 | /library/media/info/<id> 馆藏详情页（主代理补做，29 条标题可点） | 主 |
| D1 | 导航补 15 项（幂等种子脚本 scripts/seed_d1_nav.py；Placements 无开源对应跳过）；页脚联系块；根因=setup_brand_yongyue.py 曾按名删菜单 ⚠️重跑该脚本后必须重跑种子 | U |
| D3 | 分类已读语义：edu.alert.read.seen_map 水位 + 点击提醒项 fetch 上报单类清零 + 全部已读兼容 | Y |
| D5 | 解隐 订单/支付方式/DMS/资产请求/OMR×2；rfq/purchase/入场 保持隐藏（无路由，暂缓） | Y |

## 集成回归：16/16 PASS（浏览器级）
B1 页面渲染 ✓｜B3 入口+详情 ✓｜B6 下钻+结果可达 ✓｜B9 CSV+BOM ✓｜B4 tab ✓｜D3 接口+卡片带 key ✓｜D5 订单/资产卡可见 ✓｜A3 Fees 卡不回退 ✓｜教师落地不回退 ✓｜A4 按钮 5/5 ✓｜B8 点击进详情 ✓｜D1 导航抽查 6/6 ✓

## 死链终局
batch2.xml 残留 **0**；batch3.xml 残留 8 处均为合法（3 表单折叠触发器 + 5 演示按钮）。
本轮追加清扫：通知标题/申诉标题去假链接（原站本不可点）、删除媒体采购/媒体运动/创建×2 四个无后端死按钮。
数据补漏：王小明选课记录挂 14 门科目、4 本馆藏关联科目（修复科目列表空态根因）。
>
> **追加修复（用户报告：科目点不了）**：
> - `/subject/details` 科目名 href=# 死链 → 新建 `/subject/material/detail/<id>` 材料详情页（科目信息+关联馆藏列表，对齐原站 URL 模式）
> - `/subject/registration` 注册单 SR 号 href=# 死链 → 新建 `/subject/registration/data/<id>` 详情页（单据信息+已注册科目，chip 可再点进材料详情）
> - 数据补漏：王小明的选课记录未挂科目（造数遗漏）→ 挂上 14 门预备科科目、4 本馆藏关联到前四科
> - 浏览器点击回归全通；列表统计 学科 14 / 材料 4

三代理并行：S 学生门户(32行) + R 教师家长(31存档) + P 公开导航(26行)
对照基准：reference/ 与 scrape/ 原站存档 ↔ 本地实页（正确身份会话实测）

## 总量：89 行对照 → OK 28 / 死链 22 / 空壳 18 / 缺失 21

## A 包 · 快修（零成本~一行级，路由已存在或纯指向错误）
| # | 项 | 修法 |
|---|---|---|
| A1 | 铃铛"图书馆媒体请求" href 写错（/my/requested/queue/list → /requested/queue/list） | 改配置路径 |
| A2 | 图书馆"媒体队列"入口 href=#，但目标页本地已实现 | 补真实 href |
| A3 | Fees/会议/在线会议 三卡未上首页（路由本身 200） | 分组引用补上 |
| A4 | 登录页演示按钮 2/5（缺 Faculty/Parent/Backoffice） | 补三组按钮 |
| A5 | 页脚社交 ×3 死链（fb/tw/li 404） | 移除或改 # |
| A6 | 首页导航 /website/activity/announcement 404 | 移除或补路由 |

## B 包 · 需新页面/路由（按价值排序）
| # | 项 | 原站行为 | 工作量感 |
|---|---|---|---|
| B1 | **/student/progression 进展页** | 首页大卡全角色可见，当前 404 最刺眼 | 中 |
| B2 | /library/media/info/<id> 媒体详情 | 29 条媒体标题可点开 | 中 |
| B3 | /student/exam/data/<id> 考试详情 | "查看详情"开详情页 | 中 |
| B4 | 布告栏 Circular tab | 家长存档实证 | 小 |
| B5 | 数字图书馆 material/read 详情 + 游客可见性 | 29 件馆藏游客可见 | 中 |
| B6 | 测验/考试结果详情 /exam/result/<id> | 结果可下钻 | 小~中 |
| B7 | profile 动作族（技能/offer 加退/撤回/费用PDF/道歉表） | 各表单与PDF | 大 |
| B8 | /courses?course=N 详情参数 | 点课程开详情 | 小 |
| B9 | grade-book Download Report | 报告下载 | 小 |
| B10 | 代请假表单 /my/child/<id>/leave 挂入口 | 孤儿页 | 小 |

## C 包 · 数据/运营型空壳（非代码缺陷）
- /event、/blog 空（造活动/博文即可）
- /alumni 单卡无链、/courses-offered 静态卡、/online-exams 演示卡、职位卡→/jobs 空列表（造数据+小改）
- /program-offered、/booking "即将开放"占位（原站亦然，属有意）

## D 包 · 需拍板的方向决策
| # | 决策点 | 选项 |
|---|---|---|
| D1 | 首页导航缺原站 13 入口 | 补齐 vs 保持精简 |
| D2 | /web/signup 404 | 启用注册 vs 移除入口 |
| D3 | 铃铛 5 类提醒永不触发（_count_for_card 不支持） | 实现计数 vs 保持现状 |
| D4 | 即时聊天卡 href=#（原站 /student/livechat/） | 接 Odoo livechat vs 移除卡片 |
| D5 | 隐藏卡策略（edu.portal_hidden_cards：OMR/入场/资产/订单/支付/DMS/rfq/采购） | 维持隐藏 vs 逐个补路由后放开 |

## 已确认健康（抽样）
Quick actions 六按钮、统计块、profile 七 tab、各列表筛选排序、教师五大工作台、
apps_menu 25 卡、time_off 折叠表单、公开页骨架、/online-exams→/quiz 迁移等价。
