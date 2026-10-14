# LMS 在线课程 · 设计摘要与实施方案
> **状态**：`已上线` ｜ **主题**：`LMS 在线课程` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 状态：✅ 已交付（2026-08-23，真机验证+合规自检通过）｜ 工作流 `docs/dev-workflow.md` ｜ 铁律 `/Users/qwe/odoo-enterprise-ref/README.md`

## 一、参考与结论

- 参照社区版 website_slides（LGPL，合法）的「课程 channel → 课次 slide → 学员进度 slide_partner」三层概念；
  **只学结构，一行代码不搬**。
- 课程容器直接复用基座 `op.subject`（预备科 14 门即 14 门课），不新建课程表；班级归属沿用
  `op.student.course`（学生↔batch↔course 链）。

## 二、自研模型（custom_addons/edu_portal/models/lms.py）

**edu.lesson 课次**
| 字段 | 类型 | 说明 |
|---|---|---|
| subject_id | M2O op.subject, required, ondelete=cascade | 所属课程 |
| name | Char required | 课次标题 |
| type | Selection video/article, default video | 课次类型 |
| video_url | Char | 视频嵌入地址（iframe src 用） |
| content_html | Html | 文章正文 |
| sequence | Integer default 10 | 排序 |
| state | Selection draft/published, default draft | 发布状态 |

**edu.lesson.progress 学习进度**
| 字段 | 类型 | 说明 |
|---|---|---|
| lesson_id | M2O edu.lesson, required | 课次 |
| student_id | M2O op.student, required | 学生 |
| state | Selection draft/done, default draft | 完成=done |
| completed_date | Date | 完成日期 |

约束：`unique(student_id, lesson_id)`；权限方法 `mark_done()` 写 done+date。
进度百分比 = 该课程 published 课次中该生 done 占比（控制器现算，不建存储字段）。

## 三、门户三页（controllers/lms.py，四视角分流参照 scheduling.py）

| 路由 | 内容 |
|---|---|
| `/my/courses` | 课程卡列表：图占位+科目名+课次数+我的进度条；学生=本班课程，教师/内部=全部，家长=孩子课程合集，裸门户=空表 |
| `/my/courses/<int:subject_id>` | 课次列表（published，按 sequence）：类型图标+标题+完成勾；无权访问重定向回列表 |
| `/my/courses/lesson/<int:lesson_id>` | 详情：video→iframe 嵌入（仅 https），article→正文；底部「标记完成」POST |

写路由 `/my/courses/lesson/<int:lesson_id>/done`（csrf=True）：当前学生 upsert progress=done。
时间显示一律控制器预格式化（Odoo19 t-options 无 widget 键会 KeyError——上轮教训）。

## 四、后台管理（views/lms.xml）

- edu.lesson 中文 list/form（priority=1）：form 分组「内容」（type 切换显隐 video_url/content_html）+「发布」state；
- 新根菜单「在线课程」seq67 groups=base.group_user → 子菜单「课次管理」「学习进度」(progress list 只读 system)。

## 五、ACL 实际落地（deny-by-default，比初稿更严格）

| 模型 | group_user | group_system | group_portal |
|---|---|---|---|
| edu.lesson | 1/1/1/0 | 1/1/1/1 | 无行=全 0 |
| edu.lesson.progress | 1/0/0/0 | 1/1/1/1 | 无行=全 0 |

门户读写一律走控制器 `sudo()` + 服务端身份绑定（`current_student()` 由
`op.student.user_id`=uid 解析，POST 参数无法注入他人身份）；
「学习进度」菜单对 group_user 开放供教师查看。

### 独立评审记录（2026-08-23）

对照 Odoo19 源码（`odoo/orm/table_objects.py`）与 website_slides 全量源码逐文件比对：
**合规红线 PASS** —— 无任何标识符或代码段级雷同，属合法概念借鉴。
2 个 Major 访问控制缺口已修复并回归通过：
① 课次详情页补科目可见域门禁（防拼 URL 枚举课件）；
② 标记完成路由校验选课关系（防任意学生刷任意课程进度）。
同步落地的改进项：mark_done 并发竞态 savepoint 兜底、UNIQUE(subject_id,name)、
video_url CHECK https、班级无科目时不再兜底泄露全目录、进度菜单开放 group_user。

## 六、种子（scripts/seed_lms_demo.py，幂等）

取前 3 门科目各建 2-3 个【演示】published 课次（1 视频 + 1 文章；视频用占位
https://www.youtube.com/embed/ 空白 id 会黑屏 → 改用文章为主、视频给 W3C 公开示例 mp4 链接），
已存在（同名+同科目）则跳过。

## 七、涉及文件

models/lms.py＋models/__init__.py｜controllers/lms.py＋controllers/__init__.py｜views/lms.xml｜
security/ir.model.access.csv｜__manifest__.py(version→19.0.1.3.0)｜scripts/seed_lms_demo.py

## 八、验收标准（真机，2026-08-23 全部通过 ✅）

- [x] 学生 stu@local：课程列表 14 卡含进度条 → 课次列表 → 视频课次标记完成 → 进度落库 done
- [x] 教师/家长/内部三视角正常（家长页标题「孩子的课程」已核验）；裸门户账号空表
- [x] 后台「课次管理」中文视图渲染 8 条课次，可建/发
- [x] 种子双跑幂等（created=8 → created=0/skipped=8）
- [x] 合规审查：工件级 grep 零 website_slides 标识符；iframe 仅经 https 过滤的 safe_video；
      独立评审子代理报告后到作为补充归档
- [x] 截图存档 `shots/local/lms_*.png`（7 张）

> QA 过程修复两个真 bug：进度列表引用不存在的 `subject_name` 字段（升级校验失败根因）；
> 页头搜索表单吞掉同页提交（DOM 诊断后改为按 form action 精确定位）。
> 附带修复：welfare.py 旧版 `_sql_constraints` 被 Odoo19 静默忽略 → 迁移 models.Constraint。
