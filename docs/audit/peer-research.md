# 同类系统辅助功能调研（供 aux-features 路线图参考）

> 2026-08-29，调研对象：OpenEduCat、Fedena、Gibbon、RosarioSIS、openSIS、PowerSchool、Canvas LMS、Moodle + 国内（校管家/学邦/校盈易/小禾帮）。全部 URL 来自搜索/抓取结果。
> 总结论：**服务端渲染架构下，Top 价值功能几乎都是"服务端生成资源 + 普通链接/表单"模式**（导出、ics、打印视图、软删除、审计）；真正需要大量 JS 的（命令面板、拖拽排课、输入即建议）放低优先级。

## 功能 × 系统 × 适配价值

| 功能 | 参考系统（来源） | 典型交互 | 适配价值 |
|---|---|---|---|
| iCal 日历订阅 | Moodle（docs.moodle.org/en/Calendar_export）、Canvas（community.instructure.com KB 662797） | 日历页展示带 token 的 ics URL，用户粘进 Google/Outlook/手机日历 | **高**：纯服务端生成，零 JS |
| 列表批量导出 | RosarioSIS（rosariosis.com/apps/what-is-a-student-information-system）、PowerSchool Data Export Manager、Gibbon Query Builder | 列表工具栏导出按钮，带当前筛选 | **高**：SSR 易，照 CSV 范式 |
| PDF 报表/打印视图 | RosarioSIS HTML 报表、OpenEduCat（Odoo QWeb） | 生成 PDF 或打印友好 HTML | **高**：print.css 即可 |
| 文件在线预览 | Canvas DocViewer（KB 662858）、三种展示策略（下载/浮层/内联，CSU Chico KB 113494） | PDF 原生渲染/浮层预览，预览与下载分离 | **中高**：PDF 内联零 JS；Office 需转码 |
| 通知中心+未读徽章 | Moodle Notifications、Canvas 通知设置 | 铃铛+红点，按类型筛选 | 高：已有水位+私信基础，增量小 |
| 邮件通知偏好矩阵 | Canvas（立即/每日/每周/关闭）、PowerSchool 家长 Email Notifications | 事件×渠道开关矩阵 | 高：表单 SSR 易；摘要需 cron |
| 回收站/软删除 | Moodle Recycle bin（默认 7 天可配） | 列表+恢复按钮+过期 | 高：active 字段是 Odoo 惯例 |
| 操作审计（重点：成绩变更留痕） | Canvas Grade Change Activity（KB 661414）、OpenEduCat "complete audit trails" | 按人/时间/对象过滤只读日志 | 高：埋点表+查询页 SSR 易 |
| 批量导入（Excel） | Moodle Upload users、Gibbon 统一导入、Fedena Custom Import、RosarioSIS add-ons | 模板→上传→逐行校验→错误回执 | 高：两段式预览确认 |
| 收藏/置顶/最近使用 | Moodle Starred courses / Recently accessed blocks | 星标 toggle + 自动最近 | 中高：小表+2 路由 |
| 全局搜索 | Moodle Global search（按权限范围） | 顶栏常驻框，结果页分组 | 高：多表 ilike+角色过滤 |
| 截止提醒 | Canvas To-Do、Moodle 日历事件 | 到期前列表/推送 | 中高：需 cron |
| QR 限时自助签到 | Moodle Attendance（QR 轮换约 30s 防代签，UNSW 说明） | 教师展示 QR，学生扫码 | 中高：SSR 出码易，业务规则需定 |
| 图形化排课/成绩图表 | 校管家、学邦 TTPS、Gibbon 成绩追踪 | 拖拽网格/图表 | 高价值但重 JS，后置 |
| Ctrl+K 命令面板 | Odoo 19 原生（odoo.com/documentation/19.0 keyboard_shortcuts）、Canvas Gradebook j/k | 面板搜索菜单/记录 | 中：重 JS，后置 |

## 主要来源

- Moodle：docs.moodle.org/en/{Calendar_export, Global_search, Notifications, Recycle_bin, Attendance_activity, Upload_users(405), Starred_courses_block}
- Canvas：community.instructure.com KB {662797, 662858, 662894, 661414, 387069, 660826}
- PowerSchool：ps.powerschool-docs.com（Data Export Manager）、powerschool.com/solutions/communication/powerschool-mobile
- RosarioSIS：rosariosis.com/apps/what-is-a-student-information-system、rosariosis.org/add-ons
- Gibbon：gibbonedu.org/features、docs.gibbonedu.org（导入）、github.com/GibbonEdu/module-queryBuilder
- Fedena：fedena.com/feature-tour/standard-modules
- openSIS：opensis.com/features
- OpenEduCat：openeducat.org、doc.openeducat.org、newdocs.openeducat.org
- Odoo 19：odoo.com/documentation/19.0/applications/essentials/keyboard_shortcuts.html
- 国内：xiaogj.com（校管家）、xuebangsoft.com（学邦）、jgysoft.com（校盈易）、xiaohebang.cn（小禾帮）
