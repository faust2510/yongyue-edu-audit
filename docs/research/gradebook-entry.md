# 成绩中心（成绩簿）录入入口调研 —— 教务/教师两个轴 + 一科一个总分

> **调研日期**：2026-09-24
> **调研范围**：本仓 `custom_addons/`、`openeducat_erp/`（官方快照）、生产库 `edu19`（**只读**）、本地克隆库 `edu19`（**只读**）、同类开源系统与国内 SaaS。
> **调研方法**：源码阅读（给 文件:行号）+ 生产/本地库只读 SELECT（给时刻）+ 同类系统官方文档/源码 URL。
> **铁律 0 声明**：本文是「成绩中心」这一新需求的第 2 步交付物（`docs/dev-workflow.md` 六步闸门第 2 步）。**本文不含任何代码改动、不含部署、不含 commit。** 所有对生产库的访问均为只读 `SELECT`。
> **行号漂移说明**：本仓行号取自当前工作区；基座 `openeducat_erp/` 行号取自已与本地容器**逐文件 MD5 对拍一致**的快照（见 §14.1）。

> ### ⚠ 2026-10-13 补记（本会话核实，**优先于下文旧口径**）
>
> 成绩中心**已有实存实现并在生产上运行**（task-18，2026-10-03 交付）：`custom_addons/edu_portal/controllers/grade_entry.py`（620 行，路由 `/grade-entry`、`/grade-entry/save`）＋ `custom_addons/edu_portal/controllers/grading.py:56`（`/grade-book` 两态）；审计 11/11 PASS 见 `docs/audit/backend-ux/t18-independent-verification.md`。用户已于 2026-10-13 三轮访谈拍板**追认现有实现**（13 条口径见 `docs/plans/gradebook-center-design.md` §1），本文据此转为**追溯设计的依据**。
>
> **下文 4 处已失效**（读时以补记为准）：
> 1. §11（`:1257-1261`）推荐新建 `edu.grade.*` 表 —— 实存实现**不新建模型**（`grade_entry.py:1-46` 文件头写明「本仓硬口径：不新造成绩模型」），复用基座 `op.exam` 容器；
> 2. §8.2（`:1111`）的 8 条否证针对「手工凑一场考试」—— 实存实现是**程序化自建** `op.exam` 容器（`grade_entry.py:134-209`），结论不适用；
> 3. §0.1 / §2.4 的「两表之间唯一的桥 = 后台手动按钮」—— `/grade-entry/save` 已**旁路**该桥：门户自己把两侧写齐（`grade_entry.py:593/602/607`），学生页已能即时看见；
> 4. §4.3 / §9.1 / §14.5 引用的 `batch2.py:1034-1093` 行号已漂移（该文件经 commit `eb19918` 改动，`/grade-book` 现于 `batch2.py:1069`）。
>
> 本文其余部分（生产快照、基座源码、同类系统调研、取证命令与死路）**仍是有效档案**。

---

## 0. 结论速览

### 0.1 一句话回答

**「教务录进去的分，学生看不见」——但这不是权限问题，是数据链断裂。**
写入侧 `/grading/entry` 写的是 `op.exam.attendees.marks`；读取侧 `/grade-book` 与 `/my/study` 读的是 `op.marksheet.line → op.result.line`。两者之间**唯一的桥**是基座的一个**后台按钮** `op.result.template.generate_result()`，**全仓零自动调用**，而且这个按钮**按一次就把数据永久冻结**（`op.result.line` 上有 `UNIQUE (exam_id, student_id)`，第二次生成必冲突）。本地克隆库留下了实证：**同一 (exam=11, student=5)，attendee 上是 20 分，学生看到的 result_line 上是 92 分**，而且 `edu.grade.history` 在这条数据上有 **186 条**变更记录 —— 写了 186 次，学生看到的数字一次都没跟着动。

再叠加一层：用户点名的 **`/grade-book` 本身就是被设计成"仅学生"的单人页**（`batch2.py:1036` 只取 `current_student()`，路由**不接受任何学生参数**），所以**教务即便有数据也无从进入**；页面上写死的文案就是「该页面仅面向学生账号」（`views/batch2.xml:40-45`）。

### 0.2 最关键的 5 条结论（带来源）

| # | 结论 | 一手来源 |
|---|---|---|
| **1** | **读写不是同一张表，中间那座桥是一个手动后台按钮，且不可重复执行。** 桥 = `op.result.template.generate_result()`；唯一触发点 = `views/result_template_view.xml:24` 的 `<button name="generate_result" invisible="state != 'draft'">`。`op.result.line` 上 `UNIQUE (exam_id, student_id)` ⇒ 第二次生成必抛唯一冲突 ⇒ **改分之后学生看到的快照无法更新**。 | `openeducat_erp/openeducat_exam/models/result_template.py:73-101`（生成逻辑）、`result_template.py:49-55`（要求 session 下所有 exam 都 `state='done'`）、`views/result_template_view.xml:24`（按钮）、生产库实测 `op_result_line_unique_result_line UNIQUE (exam_id, student_id)`（§2.1） |
| **2** | **教务进不去有两个机制，第二个才是以后新建模型也会踩的坑。** 机制 A：`/grading/entry` 第一行就要 `current_faculty()`，教务没有 `op.faculty` 档案 ⇒ 302。机制 B（新发现）：`group_op_back_office_admin` **implies `group_op_faculty`**，而 Odoo 的 ir.rule 是「**同组内 AND、跨组 OR**」⇒ 只写「教师只看自己任教班」的行级规则会把教务**误收敛成零行**。本仓已有硬知识写在 `edu_assess/security/security.xml:23-25`，并给了正确写法（补一条恒真域，`:74-94`）。 | `custom_addons/edu_portal/controllers/roles.py:871-875`、`custom_addons/edu_portal/views/group_tuning.xml:13-26`、`custom_addons/edu_assess/security/security.xml:23-25,74-94`、`/usr/lib/python3/dist-packages/odoo/orm/models.py:5359-5366`（`active_test` 隐式过滤，见 §4.1） |
| **3** | **报课 = 已成体系的既有能力，名单事实源是 `op.student.course.subject_ids`（表 `op_student_course_op_subject_rel`），且本仓所有学生侧页面已经在用它。** 基座 `action_approve()` 与自研 `action_enroll_approve()` 都把「必修∪选修」写进这一列；`lms.py:_subjects_for()` 与 `/my/courses`、`/my/study`、`/my/study/<subject_id>` 全部以它为口径。**但生产里几乎没数据**：`op_subject_registration` 1 行（且 state=`submitted` 未审批）、`op_student_course_op_subject_rel` 2 行。 | `openeducat_erp/openeducat_core/models/subject_registration.py:64-82`、`custom_addons/edu_portal/models/registration.py:165-244`（原文注释「**档案 subject_ids 仍是 LMS/课表读取的事实源**」）、`custom_addons/edu_portal/controllers/lms.py:22-44`、生产读数（§6.4） |
| **4** | **「评估」模块（`edu_assess`）已经把本需求 80% 的形状建好了，且它就在工作区里（code-map 说 9 个 edu_* 模块，实际 13 个）。** 它有一套完整的「任务 → **名单快照** → 打分记录」三层 + 四角色 ACL + ir.rule 双层收敛 + 门户矩阵录入 + xlsx 往返。**但它评价的是"人"，不是"科目成绩"**，且生产 `edu_assess_*` 全部 0 行。 | `custom_addons/edu_assess/models/assess.py` 的 `EduAssessTask` / `EduAssessRoster` / `EduAssessScore` 三个模型、`custom_addons/edu_assess/security/ir.model.access.csv:2-16`、`custom_addons/edu_assess/security/security.xml`、`custom_addons/edu_assess/controllers/portal.py:115-132,402-487`、生产读数（§7.2） |
| **5** | **「一科一个总分」与 `op.exam` 是结构性冲突，不是配置问题。** `op.exam` 的语义单位是「**一场考试 × 一个科目**」，`op.marksheet.line.percentage` 的计算是「本 session 下**所有科目**的考试总分之和为分母」（`marksheet_line.py:65-72`）⇒ 一个 session 装多科时，学生的"百分比/等级"是**跨科目混算**的。要拿它表达「一科一个总分」，得给每科各建一个 session，然后亲手绕过它自己的计算口径。 | `openeducat_erp/openeducat_exam/models/exam.py:27-40`、`marksheet_line.py:38-50,59-72`、`custom_addons/edu_portal/controllers/study.py:186-216`（`_grade_layers` 用 `subject_id` 分桶再按满分加权，等于在控制器里**重做**了一遍口径） |

### 0.3 推荐（详见 §11）

**新建一个「成绩簿」域（前缀 `edu.grade.*`）+ 复用 `op.student.course.subject_ids` 作名单 + 复用 `edu.grade.history` 作留痕**，形态照 `edu_assess` 的三层（定义/名单/记录）抄，但**被评对象是「学生 × 科目 × 学期」而不是「人」**。
**明确不做**：把 `op.exam` 伪装成"单场考试"硬凑（§8.2 逐条否证）；把 `op.subject.registration` 直接当成绩表（§7.1 否证）；指望社区版 `spreadsheet`/`web_grid`（§8.4）。

### 0.4 对外调研结论（**本轮完成，国内同类**）

> **「按科目进入 → 该科目全班成绩单」这条轴，国内同类产品里没有一家有。**
> 钉钉（宜搭 9 个教育组件里**没有成绩 / 分数组件**；开放平台全量 API 目录"考试 / 评分 / 成绩单"命中 **0**）、飞书（官方把「成绩查询」列为**需开放平台个性化开发**的校园工具）、智学网（账号以**准考证号**为单位）、好分数（一级入口是「**考试**」，二级才是「学科分析」）、七天网络（以**考试 / 阅卷批次**为组织单元）—— **主轴一律是「按考试批次 ＞ 按班级 ＞ 按表单」，科目只是「列」或「筛选条件」**。
> ⇒ **本需求要做的是差异化能力，自研有据**（铁律 0 要求的"为何无先例"可直接引用本节）。与 `edu.grade.history` 变更留痕属同一类差异化点（国内主流普遍缺）。完整证据见 **§5.4**。

### 0.5 Moodle / Canvas 源码级复核（**本轮完成，并更正仓内假设 3 处**）

取证件坐标系：Moodle `moodle/moodle` @ `MOODLE_405_STABLE` commit `89ae02d0007418c50f0911148137f4cb3bd67f4a`；Canvas `instructure/canvas-lms` @ `stable/2026-05-20`。全部经 `raw.githubusercontent.com` HTTP 200 取回后逐行阅读（**无搜索引擎可用**）。

**最值钱的三条**（详见 §5.5.2）：

1. **Moodle `grade_grades_history` 存在，且是"整行快照"机制** —— 写入点在**父类** `grade_object` 的 `update/insert/delete` 三处，每笔写入追加一条**完整字段快照**（不是 diff），自带 `action` + `source`（manual/module/import）+ `loggeduser` + `timemodified`。⇒ **本仓 `edu.grade.history` 四要素已齐且比它多一个 `old_marks`**；新模型应额外冗余存 `batch_id_at_snapshot`/`term_id`（= 校长拍板 P5 需要的东西）。
2. **Canvas `gradebook_history` 存在** —— 是"提交版本流水"，`feed` 端点支持**正查/倒查 + 按学生或按作业过滤**。⇒ 本仓 `/grading/history` 现只有"按 exam / 按 student"两筛，**新留痕页应做到"按学生 / 按科目 / 按时间"三种可筛**（低成本、可对标）。
3. **Moodle 与 Canvas 都没有"跨课程 / 按科目"的明细聚合视图** —— Moodle 把 `course` 当科目、grader/user 报表强制单课程；Canvas 所有入口都以单个 Course `@context` 限定。⇒ 与 §0.4 的国内结论**互相印证**：**「按科目进入」在三边都没有先例，本仓自研有据。**

**更正仓内既有假设 3 处**（§5.5.1）：M1 Moodle 聚合枚举 **12=EXTRACREDIT_MEAN / 13=SUM**（既有档写反）；M2 `grade_item::set_aggregation()` **不存在**（现为 `set_aggregation_fields_for_aggregation`，真正聚合在 `grade_category`）；C1 Canvas CSV 作业列头是 **`<标题> (<作业 id>)`**，**不是满分**。

**仍未取到**（§5.5.3）：Canvas `db/schema.rb`（404 ⇒ Canvas 存储结论出自模型/控制器源码而非 DDL）、Canvas 官方 CSV 规范与 Gradebook History 的官方文档 URL 与 UI 路由、Moodle 官方文档站原文。

---

## 1. 需求拆解与用户已拍板口径

### 1.1 用户原话（逐字）

> 「假如我正在使用教务权限进入这个页面：https://edu.example.org/grade-book。我希望根据不同科目或者不同学生的划分方式进入他们的成绩中心，可以给他们各科录入成绩。」

### 1.2 需求三拆

| 代号 | 需求 | 本文落点 |
|---|---|---|
| (a) | **教务**（registrar）要能进得去 | §4（为什么现在进不去）、§9（进去之后看什么） |
| (b) | **两个入口轴**：按科目 / 按学生 | §6（名单从哪来）、§8（两条路径对比） |
| (c) | 进去能**录入各科成绩** | §7（成绩存哪）、§10（评分口径） |

### 1.3 用户后续拍板（队长转达，2026-09-24）

| # | 用户原话 | 对设计的硬约束 |
|---|---|---|
| 1 | 「我希望是**一科目的总成绩**」 | **一科一个总分**，不是多场考试加权 ⇒ **否决 `op.exam` 作为主结构** |
| 2 | 「教务系统老师可以录入」 | **教务 + 任课老师**都能录（两个角色，一个入口） |
| 3 | 「录完之后学生能够看到。不需要发布一下」 | **录完即时可见，无发布态** ⇒ 不能引入 `state=draft/published` 门；但也意味着**没有"撤回"语义**，纠错只能靠留痕 + 覆盖 |
| 4 | 「就按照以后学生报课的名单来，谁报课了就知道了」 | **名单事实源 = 学生报课记录**（§6 给出字段级答案与今日退路） |

### 1.4 与本仓既有决策的关系（**重要：与「评估」不重叠**）

仓内已有一份**明文划定边界**的设计文档，直接回答了"这事是不是已经被决策覆盖了"：

> `docs/plans/evaluation-rebuild-design.md:104`
> `| op.result.line / op.exam.attendees（成绩册） | 考试成绩：/grading/entry、/grading/export、/grading/import | 一行 = 一个学生的**一个分数**，没有评分项维度；且绑定 op.exam |`

该表的标题是「**"看起来像但不是"的 5 类，逐条否证**」——即：**评估系统重建（`edu_assess`）在立项时就明确把"成绩册"排除在外**，理由是"一行 = 一个分数、绑定 `op.exam`"，与评估的"评分项维度"不是同一个域。
该文档 `:183` 的收口触发条件 **T3** 进一步写明：「校长要求"评估结果进成绩册" ⇒ 那时评估不再是独立域 ⇒ **须重走第 0 步**」。

**结论：成绩域从未被调研过，本次是第一次。** 本文不与 `edu_assess` 的决策冲突，反而是它的对偶面（评估 = 对人的多维评分；成绩 = 对科目的一维总分）。

---

## 2. 现状：数据流图（实际字段名 + 行号 + 生产读数）

### 2.1 生产只读快照（`edu19-prod-db-1`，**读取时刻 2026-09-24 09:56:09 UTC**）

命令（只读，逐字可复现，见 §14.2）：

```sql
SELECT 'op_exam' AS t, count(*) AS n FROM op_exam
UNION ALL SELECT 'op_exam_session', count(*) FROM op_exam_session
... ORDER BY 1;
```

| 表 | 行数 | 说明 |
|---|---|---|
| `op_exam` | **0** | 一场考试都没有 |
| `op_exam_session` | **1** | id=3，name=`1`，`course_id=13`、`batch_id=34`（**总览班**）、`exam_type=1`、`state=draft`、`evaluation_type=normal`、2026-09-17~09-18 |
| `op_exam_type` | 1 | |
| `op_exam_attendees` | **0** | 一个考生都没有 |
| `op_result_template` | **0** | |
| `op_grade_configuration` | **7** | A+(90-100) / A(80-89) / B(70-79) / C(60-69) / D(50-59) / E(40-49) / F(0-39)，id 8~14 |
| `op_marksheet_register` | **0** | |
| `op_marksheet_line` | **0** | |
| `op_result_line` | **0** | |
| `edu_grade_history` | **0** | |
| `op_faculty` | **1**（active = **0**） | id=20、partner_id=65（名字「待定」）、`active=false`；其 partner 的 `user_id`=**33**（`teacher@local`） |
| `op_student` | 29 | |
| `op_student_course` | 24 | 5 名学生无学籍档案（【待分配】×5） |
| `op_student_course_op_subject_rel` | **2** | 只有学生 id=11 王佐 × {神论 56, 救恩论 68} |
| `op_subject` | 147 | |
| `op_batch` | 12 | A1/A2/A3/B1/B2/B3/B4/C·A硕/C·B硕/预科/二级本科/**总览班** |
| `op_session` | 216 | 只覆盖 5 个班：34(139)、15(40)、13(18)、20(15)、10(4) |
| `op_subject_registration` | **1** | id=19 SR0017、`state=submitted`、`doc_type=subject_registration`、学生 11、course 16、batch 13 |
| `subject_compulsory_rel` | **21** | 上面那张单的必修科目集（id 70~138） |
| `op_subject_op_subject_registration_rel` | **0** | 选修为空 |
| `edu_course_subject` | 478 | 专业 × 科目 × 必修/选修（`edu_portal`，见 `models/major_track.py`） |
| `edu_assess_*`（7 张） | **全 0** | 见 §7.2 |

> ⚠ **`op_exam_session` 唯一一行挂在 `batch_id=34 = 总览班`**，而**总览班有 0 名学生**。即使有人去建考试，也拿不到考生名单。

### 2.2 写侧：`/grading/*` —— 六个路由的守卫与读写表

全部在 `custom_addons/edu_portal/controllers/roles.py`。

| 路由 | 行号 | 守卫（第一道） | 读/写表 | 说明 |
|---|---|---|---|---|
| `GET /grading/entry` | 871-915 | `fac = current_faculty(); if not fac: → /my/home`（`:873-875`） | **读** `op.exam`（经 `_teacher_exam_domain()`）→ `op.exam.attendees`；读 `edu.grade.history` 计数 | 列表 + 录入表单 |
| `POST /grading/save` | 917-959 | 同上 + `_teacher_exam(exam_id)` 归属判定 | **写** 经 `edu.grade.history.edu_apply_marks()` → `op.exam.attendees`；**写** `edu.audit.log`（只记汇总） | 唯一单条写入口 |
| `GET /grading/export` | 2191-2220 | 同上 | 读 `op.exam.attendees` → CSV（列：学号/姓名/得分/状态/满分/及格线/考试） | |
| `POST /grading/import` | 2222-2293 | 同上 | 解析 CSV/XLSX → **预览（不落库）** | 两段式第一段 |
| `POST /grading/import/commit` | 2295-2336 | 同上 | **写** `edu_apply_marks(source='import')`，逐条 `savepoint` | 两段式第二段 |
| `POST /grading/copy_prev` | 2338-2392 | 同上 | **写** `edu_apply_marks(source='copy')`（只填空缺不覆盖） | |
| `GET /grading/history` | 2394-2437 | **`if not fac and not privileged_staff(): → /my/home`**（`:2398-2399`） | 读 `edu.grade.history` | **注意：这个路由给教务放行了，`/grading/entry` 没有** |

**关键不对称**：`grading_history` 的守卫是「教师 **或** 教务」，而 `grading_entry` / `grading_save` / `export` / `import` / `copy_prev` 五个的守卫**只有教师**。这不是疏漏的疏忽，是**有意为之**并有文档：

> `docs/ops/jiaowu-manual.md:173`
> 「用教师页面（点名 `/attendance/take`、成绩录入页） | 点进去会**自动跳回门户首页** | 这是设计：那些页面要「教师绑定」。**教务的考勤/成绩入口在后台**」

即：现行设计认为教务走**后台**（`时间表 / 考试 / 考试 · 考试参加者 · 结果行`，见 `jiaowu-manual.md:152`），不走门户的 `/grading/*`。

### 2.3 读侧：学生看成绩的三条渲染路径（**全部同源**）

| 路由 | 文件:行号 | 守卫 | 数据来源 |
|---|---|---|---|
| `GET /grade-book` | `batch2.py:1034-1093` | `student = current_student()`，**无参数、无回退** | `op.marksheet.line`（`student_id=本人`）→ `ms.result_line` → `rl.exam_id` |
| `GET /grade-book/report/download` | `batch2.py:1095-1126` | 同上 | 同上 → CSV（列：科目/考试/得分/满分） |
| `GET /users/result-overview` | `batch3.py:890-916`（`_result_items`） | `current_student()` | **同源**，注释原文「与 /grade-book 同源（`op.marksheet.line` → `result_line`）」 |
| `GET /my/study` + `/my/study/<subject_id>` | `study.py:273-348` → `_grade_layers()` `study.py:163-239` | `current_student()`（经 `_subjects_for` 的角色分支） | 同源 + 按 `ex.subject_id` 分桶 + 按 `ex.total_marks` 加权 |

**三条渲染路径的公开字段名**（`/grade-book` 表格列，`views/batch2.xml:64-80`）：科目 / 考试 / 分数 / 总分 / 百分比 / 等级 / 状态。**注意：列头就叫「考试」，不叫「学期」「科目成绩」**——这正是用户要的「一科一个总分」与现状的差。

**学生页存在一处已被代码承认的数据缺陷**（非常重要，是断层的旁证）：

> `study.py:220-228` `_sem_key()` docstring 原文：
> 「学期键：优先 marksheet 登记册；缺登记册的旧数据回落生成年份。**本库存在 `marksheet_reg_id` 为空的演示成绩（登记册未生成）**，只按登记册分组会把所有历史都并进本学期 → 用年份兜底。」

即：**代码里已经知道"成绩行可以没有登记册"**——因为演示数据是绕过 `generate_result()` 手写的（§3.4）。

### 2.4 桥：`op.result.template.generate_result()` —— 唯一的、手动的、一次性的

```python
# openeducat_erp/openeducat_exam/models/result_template.py:73-101
def generate_result(self):
    for record in self:
        marksheet_reg_id = self.env['op.marksheet.register'].create({...})   # 1 个登记册
        student_dict = {}
        for exam in record.exam_session_id.exam_ids:       # 本 session 下所有考试
            for attendee in exam.attendees_line:           # 每场考试的所有考生
                result_line_id = self.env['op.result.line'].create({
                    'student_id': attendee.student_id.id,
                    'exam_id': exam.id,
                    'marks': str(attendee.marks and attendee.marks or 0),   # ← 分数从这来
                })
                ...
        for student in student_dict:
            marksheet_line_id = self.env['op.marksheet.line'].create({...})  # 每生 1 行
            for result_line in student_dict[student]:
                result_line.marksheet_line_id = marksheet_line_id
        record.state = 'result_generated'
```

**它由谁调用？** 只有后台表单按钮：

```xml
<!-- openeducat_erp/openeducat_exam/views/result_template_view.xml:24 -->
<button string="Generate Result" type="object"
        invisible="state != 'draft'" name="generate_result"/>
```

全仓 grep（`.py`/`.xml`/`.js`/`.csv`）：`generate_result` 的**业务调用点 = 0**，只剩基座单元测试里的 `if hasattr(tmpl, 'generate_result')`（`openeducat_exam/tests/test_exam.py:328`）。**无 `create`/`write` override 自动触发。**

**前置条件链**（`result_template.py:49-55`）：

```python
@api.constrains('exam_session_id')
def _check_exam_session(self):
    for record in self:
        for exam in record.exam_session_id.exam_ids:
            if exam.state != 'done':
                raise ValidationError(_('All subject exam should be done.'))
```

而 exam 的状态机是 `draft → schedule → held → result_updated → done`（`exam.py:46-50`），每次跃迁各有 `act_schedule` / `act_held` / `act_result_updated` / `act_done`（`exam.py:150-203`）。**要做出一份学生可见的成绩，最少 6 次人工动作**（建 session → 建 exam → 建 attendees → 走完 4 步状态机 → 建 result template → 按按钮）。

### 2.5 完整数据流图（文字版）

```
【写入链】教务/教师录分
  GET  /grading/entry          roles.py:871  ← 守卫 current_faculty()（教务必被 302）
    └─ 读 op.exam  ← _teacher_exam_domain()  roles.py:842-855
    └─ 读 op.exam.attendees
  POST /grading/save           roles.py:917
    └─ edu.grade.history.edu_apply_marks()   models/registration.py:631-662   ← 唯一写入口
         ├─ write  op.exam.attendees.marks / .status
         └─ create edu.grade.history{exam_id,student_id,subject_id(related,store),
                                     old_marks,new_marks,action,source,
                                     logged_user_id,timemodified,note}
  POST /grading/import/commit  roles.py:2295   （source='import'）
  POST /grading/copy_prev      roles.py:2338   （source='copy'）
  ── 后台直写也留痕：source='backend'（t34 F1） ——
  ※ op.exam.attendees.marks 的**任何**改动都在 edu.grade.history 里留痕

        ↓ ↓ ↓   ✄ 断层在这里 ✄   ↓ ↓ ↓
        （唯一连接器 = 人工按按钮 op.result.template.generate_result()）

【读取链】学生看成绩 —— 三条路由全部同源
  GET /grade-book          batch2.py:1034   守卫 current_student()
    └─ op.marksheet.line (student_id=本人)          ← 教务进来 = 空集
         └─ ms.result_line  (op.marksheet.line.result_line)
              └─ rl.exam_id → op.exam.subject_id / .total_marks / .min_marks
  GET /grade-book/report/download  batch2.py:1095  （同上 → CSV）
  GET /users/result-overview       batch3.py:890   （同上）
  GET /my/study[+ /<subject_id>]   study.py:163-239 _grade_layers()
    └─ 同源，再按 ex.subject_id 分桶、按 ex.total_marks 加权

【旁支】评估（edu.assess.*）—— 与人相关，与科目成绩无关
  edu.assess.template → .item → .task → .roster → .score
  名单来自 scope_batch_ids / scope_program_ids（`assess.py` 的 `EduAssessTask._roster_students` / `EduAssessTask._roster_faculties`），**不来自报课**
  ※ 生产全 0 行；本文只把它当**实现形态的先例**引用（§7.4）
```

---

## 3. 断层分析：**教务录进去的分，学生到底看不看得见？**

### 3.1 确定性答案

> **看不见 —— 除非有人手工去后台按那个按钮，而且按完就永久冻结、改分也无法更新。**

**准确表述（避免过头）**：分**没有丢**，它稳稳地存在 `op.exam.attendees.marks`，并且每一次改动都在 `edu.grade.history` 里有记录。但学生的三个成绩页（`/grade-book`、`/users/result-overview`、`/my/study`）读的是**另一套表**（`op.marksheet.line` / `op.result.line`），这套表**只能由后台按钮一次性生成**。所以：

- **不按按钮 ⇒ 学生看到空页**（生产现状：`op_marksheet_line` = 0）。
- **按了按钮 ⇒ 学生看到按的那一刻的快照，之后教务再怎么改分都不更新**（唯一约束挡死了重新生成）。

下面给出四条互相独立的证据链。

### 3.2 证据链 A（代码）：不存在任何自动同步路径

| 检查 | 命令 / 文件 | 结果 |
|---|---|---|
| `generate_result` 的调用点 | `grep -rn "generate_result" --include=*.py --include=*.xml .` | **0 个业务调用**；只有 `result_template.py:73` 的定义、`views/result_template_view.xml:24` 的按钮、`tests/test_exam.py:328` 的 `hasattr` 探测 |
| `op.result.line` 有没有 `create`/`write` override | 读 `models/result_line.py` 全文（83 行） | **无**。全文只有 `_check_marks` / `_compute_grade` / `_compute_status` 和一个 no-op 的 `unlink`（`:82-83`） |
| `op.marksheet.line` 有没有 override | 读 `models/marksheet_line.py` 全文（95 行） | **无** |
| `op.exam.attendees` 有没有 override 触发同步 | 读 `models/exam_attendees.py` 全文（89 行） | **无**。只有 `_onchange_marks`（`:49-56`，只改 `exam.results_entered` 这个布尔）与 `_check_marks` |
| `op.marksheet.register` 有没有自动生成 | `models/marksheet_register.py`（90 行） | **无**。只有 `action_validate` / `act_cancel` / `act_draft` 三个纯状态按钮 |
| 有没有 cron / 自动化规则 | `grep -rn "marksheet\|generate_result\|result_template" .` 的完整文件清单 | 命中的非文档文件里**没有任何 `data/*.xml` cron 定义** |

### 3.3 证据链 B（本地克隆库实测）：同一条数据，两个不同的分

**这是最锋利的一条。** 本地克隆库 `edu19-clone-db-1` 上（**读取时刻 2026-09-24 09:53:57 UTC**，只读）：

```
op_exam_attendees ： id=11, exam_id=11, student_id=5, marks=20, status=present
op_result_line    ： id=11, marksheet_line_id=7, exam_id=11, student_id=5, marks=92, status=pass
edu_grade_history ： exam_id=11, student_id=5, n=186, source∈{backend,manual}, action∈{create,update}
                    时间跨度 2026-09-12 06:08:33 ~ 2026-09-17 01:45:46
op_result_template： 0 行
op_marksheet_register： 0 行
op_marksheet_line ： id=7, marksheet_reg_id=NULL, student_id=5, total_marks=92, percentage=92
```

**同一 (exam=11, student=5)：**
- 写入侧（`op.exam.attendees`）= **20 分**
- 读取侧（`op.result.line`）= **92 分**
- `edu.grade.history` 在这条数据上有 **186 条**变更记录（说明有人在这条数据上反复改了 186 次）
- **`op.result_template` = 0 行、`op_marksheet_register` = 0 行** ⇒ 桥**从未被建立**；`op_marksheet_line.marksheet_reg_id = NULL` ⇒ 这行成绩**没有登记册**，正是 `study.py:220-228` 注释里描述的那种"手写成绩"

⇒ **186 次写入，读取侧一次都没跟着动。**

### 3.4 证据链 C（代码考古）：演示成绩是"手写"出来的，从来没过桥

| 位置 | 原文 / 行为 |
|---|---|
| `custom_addons/seed_batch2.py:189-261` | 注释小标题「2) 成绩单：grade 配置 → result template → marksheet register/line/result」。它**逐层手工 create** 四张表。过程中写到：「结果模板要求考试 state=done；批次1的种子考试是 result_updated」，于是它直接 `session.exam_ids.write({'state': 'done'})`（`:196-199`）**强改状态绕过约束**，再 `mk_sp(env['op.result.template'], {... 'state': 'result_generated'})` **直接写成已完成态**（`:224-230`）——**完全跳过 `generate_result()`**。 |
| `scripts/seed_yongyue_data.py:379-391` | 同样直接 `S('op.marksheet.line').create({...})`，register 为空。这一处正对应本地库那行 `marksheet_reg_id = NULL` 的数据。 |
| `custom_addons/seed_batch3.py`、`custom_addons/edu_telegram/controllers/main.py:1055` | 另有两处直接读/建 marksheet 演示数据。 |

> ⚠ **路径已变（2026-10-02）**：上表引用的 `custom_addons/seed_batch2.py` / `custom_addons/seed_batch3.py`
> 已迁到 `scripts/seed_batch2.py` / `scripts/seed_batch3.py`（**内容未改**）。
> 本文是**取证记录**，按本仓铁律不回头改引用原文，只加此注记 —— 照原文路径去找会找不到文件。

⇒ **本仓的「学生能看到成绩」这个演示效果，是用脚本绕过桥手搓出来的**。这也是为什么 `seed` 出来的环境看起来正常、而生产（没人手搓）全 0。

### 3.5 证据链 D（生产库约束实测）：桥是"写一次就锁死"的

在生产库 `pg_constraint` / `pg_indexes` 实测（只读，2026-09-24）：

| 约束 | 定义 | 后果 |
|---|---|---|
| `op_result_line_unique_result_line` | `UNIQUE (exam_id, student_id)` | `generate_result()` 对同一场考试**第二次执行必抛唯一冲突** |
| `op_exam_attendees_unique_attendees` | `UNIQUE (student_id, exam_id)` | 考生行本身唯一 |
| `op_exam_unique_exam_code` | `UNIQUE (exam_code)` | 考试编号唯一 |
| `op_exam_session_unique_exam_session_code` | `UNIQUE (exam_code)` | session 编号唯一 |
| `op_marksheet_line` 上**没有**任何 `(register, student)` 唯一约束 | — | 与上面配合时，先撞 `op.result.line` 的唯一约束 |

再加上按钮的 `invisible="state != 'draft'"`（`result_template_view.xml:24`）——`generate_result()` 结尾把 `record.state = 'result_generated'`（`result_template.py:101`），**按钮随即消失**。想再生成只能新建一个 `op.result.template`，而它会立刻撞上 `op.result.line` 的 `UNIQUE(exam_id, student_id)`。

⇒ **语义结论：学生看到的成绩是"一次写死"的历史文物，不是"当前分数"。** 这与用户第 3 条口径「录完之后学生能够看到，不需要发布」是**直接冲突**的——用户要的是"录完就能看到当前值"，现行机制给的是"某个瞬间的快照，且改不动"。

### 3.6 断层的确切位置（一句话）

> 断层在 `op.exam.attendees.marks`（写）与 `op.result.line.marks`（读）之间，**唯一连接器是 `op.result.template.generate_result()` 这个后台按钮**；它既**不是自动的**（无 override / 无 cron）、又**不是幂等的**（`UNIQUE(exam_id, student_id)`）。

---

## 4. 「教务进不去」的确切位置 —— **两个**机制

### 4.1 机制 A：`current_faculty()` 为空（队长已实测，本文补齐源码级根据）

```python
# custom_addons/edu_portal/controllers/roles.py:871-875
@http.route('/grading/entry', type='http', auth='user', website=True)
def grading_entry(self, **kw):
    fac = current_faculty()
    if not fac:
        return request.redirect('/my/home')     # ← 教务在这里被弹回
```

`current_faculty()`（`roles.py:293-301`）→ `_profile_of_current_user('op.faculty')`（`roles.py:257-276`）→ `profile_of_user(env,'op.faculty')`（`edu_schedule/models/identity.py:94-108`），是**双向并集**：

```python
rec = Rec.search([(direct, '=', uid)], limit=1)              # 链① op.faculty.user_id == uid
if not rec:
    rec = Rec.search([(partner_field + '.user_ids', 'in', [uid])], limit=1)   # 链②
```

**两条链都必须跨过 `active = True` 这道隐式过滤。** Odoo 19 源码（本地容器 `/usr/lib/python3/dist-packages/odoo/orm/models.py:5359-5366`）：

```python
if (
    self._active_name
    and active_test
    and self.env.context.get('active_test', True)
    and not any(leaf.field_expr == self._active_name for leaf in domain.iter_conditions())
):
    domain &= Domain(self._active_name, '=', True)
```

⇒ `identity.py` 的两个 domain **都不含 `active`** ⇒ Odoo 自动补上 `active = True`。而生产：

| 事实 | 读数 |
|---|---|
| `op_faculty` 总行数 | 1（id=20，partner=65 名「待定」） |
| `op_faculty.active` | **false** |
| partner 65 的 `user_id` | 33（`teacher@local`，active） |
| 教务账号 uid 2/12/18 名下的 `op_faculty`（链①或链②） | **0** |

**双重后果（这比"教务进不去"更严重）**：
1. 教务 uid 2/12/18 ⇒ 两条链都查不到 ⇒ `/grading/entry` **302**。
2. **连 `teacher@local`（uid 33）也进不去** —— 它唯一挂着的 `op.faculty` 是 `active=false`，被 `active_test` 过滤。⇒ **生产上 `/grading/entry` 对"任何人"都是死路由。**
   （旁证：`docs/plans/ux-v3-delivery.md:575` 早已记录「生产上原本没有任何教师账号……`op_faculty` 仅 1 条**「待定」且未绑定任何账号**，而 216 节课全挂在它名下 ⇒ 老师无法登录、看不到「我的教学安排 / 点名 / 成绩录入」」。）

### 4.2 机制 B：ir.rule 的「跨组 OR」会把教务误收敛成零行（**新发现，设计时必踩**）

`custom_addons/edu_portal/views/group_tuning.xml:13-26` 给教务组补了一批业务管理组，其中 `:24-25`：

```xml
(4, ref('openeducat_exam.group_op_exam_user')),
(4, ref('openeducat_exam.group_op_exam_admin'))
```

而 `:16`：

```xml
(4, ref('openeducat_core.group_op_faculty')),
```

⇒ **`group_op_back_office_admin` 里的人是 `group_op_faculty` 的成员。** 本仓已把这个坑写成硬知识：

> `custom_addons/edu_assess/security/security.xml:23-25`（原文）
> 「**教务/系统**：显式"全行通过"规则。为什么必须有它 —— **Odoo 的规则组合是「同组内 AND、跨组 OR」**：一个既在教师组又在教务组的人，若只有规则 2，会被**误收敛**成"只看自己任教班"。补一条恒真域即可让 OR 命中它。」

而"教师只看自己任教班"的收敛依据是 `user.edu_taught_batch_ids`（`edu_assess/models/assess.py` 的 `ResUsers.edu_taught_batch_ids`，实现见 `ResUsers._compute_edu_taught_batch_ids`），它由 `op.session.faculty_id` 反查：

```python
fac = Faculty.search([('user_id', '=', user.id)], limit=1)
batches = Session.search([('faculty_id', '=', fac.id)]).mapped('batch_id') if fac else browse()
```

**教务没有 `op.faculty` ⇒ `fac` 为空 ⇒ `edu_taught_batch_ids` 为空 ⇒ 若新模型只写了教师行级规则，教务拿到的是 0 行**（不是全部）。

**正确写法（照抄先例，不要重踩）**：`edu_assess/security/security.xml:74-94` 给教务 + 系统管理员各补一条 `domain_force = [(1, '=', 1)]` 的恒真域规则。并且控制器侧也要同构写一遍：

> `edu_assess/controllers/portal.py:402-413`（原文注释）
> 「⚠ 这里返回的是"控制器口径"，与 security/security.xml 的行级规则**故意同构**：两层都要写。」

```python
def _teacher_roster_domain(self, task):
    if _is_school_admin():        # 教务/超管 → 不限
        return []
    fac = _current_faculty()
    if not fac:
        return [('id', '=', 0)]
    return [('batch_id', 'in', _taught_batch_ids(fac))]
```

### 4.3 顺带：`/grade-book` 对教务的真实行为（不是报错，是"静默空页"）

`batch2.py:1034-1093` 的 `grade_book()` **不接受任何参数**（签名只有 `**kw`），逻辑是：

```python
student = current_student()          # 教务 → None
lines = []
if student:
    lines = env['op.marksheet.line'].sudo().search([('student_id','=',student.id)], ...)
# student 为 None ⇒ lines 恒为空 ⇒ cards=[] ⇒ has_records=False
```

模板 `views/batch2.xml:40-45` 对 `not student` 有专门分支，**文案写死**：

> 「该页面仅面向学生账号。您当前以教师身份登录，请返回门户首页查看批阅与统计功能；如需代学生操作，请联系管理员。」

⇒ 教务打开 https://edu.example.org/grade-book 看到的是这句话 + 一个「返回门户首页」按钮。**HTTP 200，不报错**——所以从外部看像"页面坏了"，实际是**设计上就没有教务视角**。

**另需注意**：`op.marksheet.line` / `op.result.line` 的 ACL（`openeducat_exam/security/ir.model.access.csv:13-16,21-22`）只给 `group_op_exam_user`/`group_op_exam_admin`，**门户学生一行都没有**（第 21-22 行虽然叫 `..._student`，实际 `group_id` 仍是 `group_op_exam_admin`，是基座命名缺陷）。⇒ **学生看成绩 100% 经控制器 `sudo()`，不经 ACL。** 这一点对 §9 的改造范围判定很关键：**读侧的改造是纯控制器 + 模板，不需要动 ACL。**

---

## 5. 外部同类系统调研

> 本节分三部分：**5.1-5.2 = 本次独立源码级复核（本轮完成）** —— 直接 `curl` GitHub raw 源码、本地 `nl -ba` 编行定位，**且含"更正仓内既有假设"两处**；**5.3 = 仓内既有调研的复核引用**（原始 URL 由前次调研核验）；**5.4 = 本次独立取证（国内同类）**；**5.5 = 对外调研的纠错与对本仓的直接影响**。凡未亲验者一律标「未验证」。

### 5.1 Moodle gradebook（**本轮源码级复核完成**）

> **取证坐标系（行号可核对）**：repo `moodle/moodle`，分支 `MOODLE_405_STABLE`，**commit `89ae02d0007418c50f0911148137f4cb3bd67f4a`**。全部结论来自 `raw.githubusercontent.com` HTTP 200 取回后的本地逐行阅读，**未使用任何搜索引擎**。

#### 5.1.1 `grade_items.itemtype` 的真实枚举（**4 个值，不是建表注释里那串**）

建表注释写的是 `'mod', 'blocks', 'import', 'calculated' etc`（`lib/db/install.xml#L1995`），但**代码里真正判等的只有 4 个值**，全在 `lib/grade/grade_item.php`：

| 值 | 判定函数 | 行号 | 含义 |
|---|---|---|---|
| `mod` | `is_external_item()` | L1178-L1180 | 来自活动模块（forum / quiz / assignment） |
| `manual` | `is_manual_item()` | L1160-L1162 | **教师手工加的成绩项** ← 与本需求最相关 |
| `category` | `is_category_item()` | L1142-L1144 | 类别汇总列 |
| `course` | `is_course_item()` | L1151-L1153 | 课程总成绩列 |

另有 `is_calculated()`（L1255）—— 它**不是 itemtype**，而是"calculation 字段非空"。
配套字段：`itemmodule`（模块名）/ `iteminstance`（模块实例 id）/ `itemnumber`（同一活动的第几项）（`install.xml#L1996-L1998`）；`grademax`/`grademin` 默认 100/0（L2003-L2004）；`aggregationcoef` = 类别权重或其它聚合系数、`aggregationcoef2` = 带权重的额外学分场景（L2010-L2011）；`gradepass` = 及格线（L2007）；`hidden` = `1 隐藏，>1 是"隐藏到某时间戳"`，`locked`/`locktime` 同构（L2015-L2017）。

#### 5.1.2 `grade_grades`：被评人**存在表里**，唯一性是**硬约束**

- **`userid`**（`install.xml#L2042`，注释 "The user who this grade is for"）—— 被评人就在表里。
- 唯一性是**数据库硬约束**，不是应用层约定（`install.xml#L2070`）：
  ```xml
  <KEY NAME="userid-itemid" TYPE="unique" FIELDS="userid, itemid" COMMENT="one entry per user per item"/>
  ```
- 其余关键列：`rawgrade`(L2043) / `rawgrademax|min`(L2044-L2045)——**记录"存分当时的满分"**（老师可能事后改活动满分）；`finalgrade` = "cached 计算后的最终分"(L2048)；`usermodified` = 最后改动者(L2047)；`overridden`/`excluded` 都是"0 或时间戳"(L2053-L2054)；`aggregationstatus`(unknown/dropped/novalue/used) 与 `aggregationweight`(L2061-L2062) 记录这一分在聚合时**是否被采用、贡献百分比**。

#### 5.1.3 `grade_letters` 是否"只用于显示" → **是，纯显示**（三条独立证据）

1. 表注释即 "Repository for grade letters"；字段只有 `contextid`（注释："for now these will always be courses, but later..."）、`lowerboundary`（注释："Its upper boundary is the lower boundary of the next highest letter, unless there is none above, in which case it's grademax for that grade_item"）、`letter`（"Can be any character or string (OK, A, 10% etc..)"）（`install.xml#L2478-L2491`）。
2. **唯一消费点是显示函数**：`grade_format_gradevalue_letter()`（`lib/gradelib.php#L929`）← `grade_get_letters()`（#L1001）← `get_records('grade_letters', ..., 'lowerboundary DESC')`（#L1022），被 `GRADE_DISPLAY_TYPE_LETTER / REAL_LETTER / LETTER_REAL / LETTER_PERCENTAGE / PERCENTAGE_LETTER` 五种**展示**类型调用（#L847-L872）；`$displaytype` 的 docblock 原文就是 "type of display"（#L813）。
3. **反证**：`grade_letters` 在 `grade_item.php` / `grade_grade.php` / `grade_category.php` 中**一次都没出现**（全文件 grep 零命中）—— **字母不参与任何计算**。

两个增量：(a) 字母可挂在**系统 / 课程类别 / 课程**三个层级（`grade/edit/letter/index.php#L53-L75` 按 contextlevel 分支），支持"课程覆盖站点默认"；(b) 管理权限是独立能力 `moodle/grade:manageletters`（#L40-L44）。

#### 5.1.4 ★ `grade_grades_history` —— **存在，且是"全表通用机制"**

**表存在**：`install.xml#L2187-L2228`，注释 `COMMENT="History table"`。

| 列 | 行号 | 注释原文 / 含义 |
|---|---|---|
| `action` | L2190 | created / modified / deleted constants |
| `oldid` | L2191 | 指向被记录的原记录 id |
| `source` | L2192 | **"What caused the modification? manual/module/import/..."** |
| `loggeduser` | L2194 | **"the userid of the person who last modified"** |
| `timemodified` | L2193 | 改动时间 |
| `itemid` / `userid` | L2195-L2196 | 哪个成绩项的哪个学生 |
| rawgrade…finalgrade | L2197-L2202 | **改后整套分数字段快照** |
| `overridden` / `excluded` / `feedback` | L2207-L2209 | 改后状态快照 |

**不只成绩有历史**：同类 `_history` 表还有 `grade_items_history`(L2136)、`grade_categories_history`(L2103)、`grade_outcomes_history`(L2076)、`scale_history`(L1000)。

**写入点不在子类，而在父类 `grade_object`，三处**（`lib/grade/grade_object.php`）—— `update()` L244（L254 先 `update_record`，紧接 L257 `if (empty($CFG->disablegradehistory))` → L259-L264 填 `action/oldid/source/timemodified/loggeduser` 后 `insert_record($this->table.'_history', $data)`）、`insert()` L341（L358-L366 同构，action=INSERT）、`delete()` L280（L291-L300 同构，action=DELETE）。
⇒ **每一笔成绩写入都会往 `grade_grades_history` 追加一条完整字段快照行（不是只存 diff），自带"谁 / 何时 / 来源 / 动作"四要素**；全局开关 `$CFG->disablegradehistory`。

**教师网格改分会落到这条链上**：`grade_report_grader::process_data` → `$gradeitem->update_final_grade($userid, $finalgrade, 'gradebook', ...)`（`grade/report/grader/lib.php#L329`，注意 source 字面量是字符串 `'gradebook'`）→ `grade_item::update_final_grade()`（`lib/grade/grade_item.php#L1831`），其 docblock（#L1815-L1819）原文：

> "this is a only way to update final grades from gradebook and import **because it logs the change in history table** and deals with overridden flag. This flag is set to prevent later overriding from raw grades submitted from modules."

同函数 #L1878-L1880：`if ($this->is_overridable_item() && $this->markasoverriddenwhengraded) { $grade->overridden = time(); }` —— **手工改分自动打上 override 时间戳，防止模块回写覆盖**。

#### 5.1.5 ★ **更正仓内既有假设两处**（`evaluation-rebuild.md` §4.1 未覆盖 / 有出入）

| # | 仓内既有假设 | 本轮源码实测 | 依据 |
|---|---|---|---|
| M1 | 聚合枚举 "0 mean / 10 weighted mean / **12 sum / 13 extra credit**" | **12 = `EXTRACREDIT_MEAN`（含额外学分的平均），13 = `SUM`（求和）** —— 12 与 13 的语义**写反了** | `lib/grade/constants.php#L33-L73` 实测：MEAN=0(#L33)、MEDIAN=2、MIN=4、MAX=6、MODE=8、WEIGHTED_MEAN=10、WEIGHTED_MEAN2=11、**EXTRACREDIT_MEAN=12**(#L68)、**SUM=13**(#L73) |
| M2 | `grade_item.php` 里有 `set_aggregation()` / `aggregate_grades()` | **`set_aggregation()` 这个函数不存在**；现版本是 `grade_item::set_aggregation_fields_for_aggregation($from, $to)`（#L1609-L1646，docblock #L1595-L1603 说明**本方法不落库**，需自行 `update()`）。真正的聚合实现在 **`grade_category`**：`aggregate_grades()`(#L605，私有)、`aggregate_values_and_adjust_bounds()`(#L1028)、`aggregate_values()`(#L1504)、`apply_limit_rules()`(#L1781，对应建表 `keephigh`/`droplow`，`install.xml#L1975-L1976`)、入口 `generate_grades()`(#L488) | 同上链接 |

#### 5.1.6 三个视图的数据来源（**全部要求 `?id=<courseid>`**）

| 视图 | URL | 取数 | 分页 |
|---|---|---|---|
| **教师网格 grader** | `/grade/report/grader/index.php?id=<courseid>` | **行** = `load_users()`（`grade/report/grader/lib.php#L406`），SQL 在 #L464-L479，从 `{user}` 出发 join 选课与 `role_assignments`（按 `gradebookroles` 过滤"可评分角色"）；**列 / 分数** = `load_final_grades()`（#L571），SQL #L584-L587 就是朴素两表：`SELECT g.* FROM {grade_items} gi, {grade_grades} g WHERE g.itemid = gi.id AND gi.courseid = :courseid` | **有**。`$page`(#index.php L36)、`perpage`(#L51)、用户偏好 `grade_report_studentsperpage`(#L83)；`const PAGINATION_OPTIONS = [20, 100]`(#lib.php L120)、`get_max_students_per_page()`(#L549)；实际分页靠 `get_records_sql($sql,$params, $studentsperpage*$this->page, $studentsperpage)`(#L484) |
| **学生看自己** | `/grade/report/user/index.php?id=<courseid>&userid=<uid>` | `graded_users_iterator`(#index.php L139)；权限分三档：`moodle/grade:viewall` / 本人 `moodle/grade:view`+课程 `showgrades` / 家长（#L62-L71） | 不用分页（单人） |
| **学生看所有课** | `/grade/report/overview/index.php?id=<courseid 可为 SITEID>&userid=<uid>` | `setup_courses_data()`（`grade/report/overview/lib.php#L184`）**遍历该用户所有课程**，每门课取 `grade_item::fetch_course_item($course->id)`(#L219) + `new grade_grade(array('itemid'=>$courseitem->id,'userid'=>$this->user->id))`(#L222) —— **只取每门课的"课程总成绩"一行，不展开明细**；排名 SQL #L256-L259 | 不分页 |

#### 5.1.7 有没有"按科目视图"？—— **Moodle 没有**

grader 与 user 报表都强制 `required_param('id', PARAM_INT)` **单课程**（`#index.php` L35 / L30）；overview 是跨课程的**但列只有"课程 + 总成绩 + 排名"**。
⇒ **Moodle 没有"跨课程 / 按科目"的明细聚合视图** —— 它**把 course 当科目**。
容易被误认为"科目视图"的两个真实存在物：(a) grader 内部的**按类别折叠视图** `get_category_view_mode_link()`（`grade/report/grader/lib.php#L2068`）；(b) overview 的 mygrades 入口（`overview/index.php#L66`）。

#### 5.1.8 CSV：**行=学生、列=成绩项**的矩阵；导入用**列映射表单**（不是自动识别列名）

**导出**（`grade/export/txt/grade_export_txt.php#L47-L123`）：表头 = 用户资料列 + **每个成绩项一列** + 末列 `Time exported`(#L80)。
- 用户资料列由 `$CFG->grade_export_userprofilefields` 决定，**默认值** `'firstname,lastname,idnumber,institution,department,email'`（`admin/settings/grades.php#L60-L63`）；若 `onlyactive` 为假则多一列 `Suspended`(#L66-L68)。
- **成绩项列名规则**：`format_column_name()`（`grade/export/lib.php#L268-L281`）产出 `get_string('gradeexportcolumntype','grades')`，该串定义为 **`'{$a->name} ({$a->extra})'`**（`lang/en/grades.php#L286`），`extra` ∈ `Real`/`Percentage`/`Letter`/`Feedback` ⇒ **表头形如 `Quiz 1 (Real)`**。

**导入**（`grade/import/csv/classes/load_data.php`）：**上传后弹"列映射"表单**，把用户选的 mapping 组成 `$map`(#L464-L474)，并**检测映射冲突**（同一目标映射两次 → `cannotmapfield`，#L478-L490）。
- **可映射的学生身份列只有四个**（#L386-L403 硬编码）：`userid`→user.id、`useridnumber`→user.idnumber、`useremail`→user.email、`username`→user.username。
- 其余列的映射标识（源码注释 #L512-L518 原文）：`1) userid, useridnumber, usermail, username - used to identify user row`、`2) new - new grade item`、`3) id - id of the old grade item to map onto`、`4) feedback_id - feedback for grade item id` ⇒ `new` = 按列标题**新建**成绩项（`itemname = $header[$key]`，#L196）、`feedback_<itemid>` = 该成绩项的评语、`<itemid>` = 写入已有成绩项、`0` = 忽略。
- 空值 / 短横线 `-` → `finalgrade = null`（#L206-L213）。
- 落库前先进临时表 `grade_import_values` / `grade_import_newitem`，再由 `grade_import_commit($courseid, $importcode)` 提交并清理（`grade/import/lib.php#L24-L32, L46, L227-L232`）。

⇒ **Moodle CSV = "行=学生、列=成绩项"的矩阵，导入按学生定位、按列映射到成绩项。**

### 5.2 Canvas Gradebook（**本轮源码级复核完成**）

> **取证坐标系**：repo `instructure/canvas-lms`，**分支 `stable/2026-05-20`**（该仓库**已无无日期的 `stable` 分支**，只有 `stable/YYYY-MM-DD` 周更分支；已用 GitHub branches API 逐页确认为最新一版）。**注意：本次未取到 `db/schema.rb`（404）**，故下列存储结论全部来自**模型与控制器源码**，**不是建表 DDL**（见 §5.5 U-C1）。

#### 5.2.1 ★ `gradebook_history` —— **存在，是"提交版本流水"，能回答"谁何时把谁的哪个作业从 X 改成 Y"**

- 控制器头注释（`app/controllers/gradebook_history_api_controller.rb#L21-L25`）原文：
  > "API for accessing the versioned history of student submissions **along with their grade changes**, organized by the date of the submission."
- 鉴权：#L209 `class GradebookHistoryApiController < ApplicationController`；#L210-L211 `before_action :require_context` / `:require_manage_grades`（后者实现为 `authorized_action(@context, @current_user, :manage_grades)`，#L316-L318）。
- **四个端点**：#L222 `days`（"日期 → 评分人 / 作业"分组）、#L239 `day_details`、#L262 `submissions`（"Gives a nested list of submission versions"）、#L294 `feed`（"Gives a paginated, uncollated list of submission versions"，可只按 `assignment_id` 或 `user_id` 过滤、可 `ascending`）。
- **数据来源**（#L298-L309）：`SubmissionVersion.where(context_type: "Course", context_id: @context)` → `indexed_versions.filter_map(&:version)` —— 即 **submission 版本表 + 一个供成绩历史查询的索引模型**。
- **记录什么**（`@model SubmissionVersion` 定义在 #L70-L206，字段即 API 契约）：`current_grade`(#L90)、`current_graded_at`(#L95)、`current_grader`(#L100)、`graded_at`(#L110)、`grader`(#L115)、`grader_id`(#L120)、`new_grade`(#L130)、`new_graded_at`(#L135)、`new_grader`(#L140) —— **谁（`grader_id`/`grader`）、何时（`graded_at`）、改成什么（`new_grade`/`current_grade`）三要素齐全**。
- 版本本体：`app/models/submission.rb#L563` `simply_versioned explicit: true,`（提交被版本化）。
- **URL**：`/api/v1/courses/:course_id/gradebook_history/...`（helper `api_v1_gradebook_history_url` #L223、`..._for_day_url` #L241、`..._submissions_url` #L264、`..._feed_url` #L306）。

#### 5.2.2 Canvas 的分数存储：**一张 `scores` 表承载三层粒度**

`app/models/score.rb#L21` `class Score < ApplicationRecord`；#L24 `belongs_to :enrollment`；#L25 `belongs_to :grading_period, optional: true`；#L26 `belongs_to :assignment_group`。分数列四个（#L32-L37）：`current_score`、`unposted_current_score`、`final_score`、`unposted_final_score`，另有 `override_score`；#L94 `effective_final_score = override_score || final_score`。
**粒度由 `scorable` 决定**（#L102-L105）：`def scorable; grading_period || assignment_group || enrollment.course; end` —— **同一张表既可存"课程总分"、也可存"评分周期分"、也可存"作业组分"**。
⇒ **单个作业的分数不在 `scores` 表**，而在 submission（#L244 查询里出现 `submissions.score`、`submissions.graded_at`）。

#### 5.2.3 ★ **更正**：Canvas CSV 的作业列头是 `<标题> (<作业 id>)`，**不是** `<标题> (<满分>)`

**导出**（`lib/gradebook_exporter.rb#L150-L182`）：列头实测为

```
[Student]  ID  [SIS User ID]  SIS Login ID  [Integration ID]  Section  <自定义列…>  <作业列…>  <总计列…>
```

- #L152 `header = @options[:show_student_first_last_name] ? ["LastName","FirstName"] : ["Student"]`；#L153 `"ID"`；#L155 `"SIS Login ID"`；#L158 `"Section"`（`SIS User ID`/`Integration ID` 视选项在 #L154/#L156）。
- **作业列头**：`header.concat assignments.map(&:title_with_id)`（#L164），而 `app/models/abstract_assignment.rb#L2266-L2274` 的 `title_with_id` 实现就是 **`"#{title} (#{id})"`** ⇒ **括号里是作业 id，不是满分**。
- 满分**单独占一行**（只读行）：#L238 `row.concat(assignments.map { |a| format_numbers(a.points_possible) })`。
- 总计列：`points: ["Current Points","Final Points"]`（#L35）；带作业组 / 评分周期时形如 `"Assignment Group 1 Current Score (Fall 2020)"`（#L58-L71 的 `buffer_column_headers`）。

**导入**（`lib/gradebook_importer.rb`）：
- #L500-L513 硬编码白名单：学生列 + `NON_ASSIGNMENT_COLUMN_HEADERS = ["Current Score","Current Points","Current Grade","Final Score","Final Points","Final Grade","Override Score","Override Grade","Override Status"]`。
- #L515-L521 先 `shift` 掉学生列，再用 `grep_v` 正则剔除非作业列。
- #L529-L544 `parse_assignments`：**逐列**调 `Assignment.title_and_id(name_and_id)`（`abstract_assignment.rb#L2280-L2295`，正则 `/\A(.*)\s\((\d+)\)\z/`）从表头**抽出 assignment id**，用 id 找作业；`# backward compat` 兜底是"按标题精确匹配"；仍找不到则 `Assignment.new(title: ...)` + `NegativeId.generate` 造一个虚拟新作业（#L536-L538）。
⇒ **按列（作业）匹配、按行（学生）定位；匹配主键是列头括号里的作业 id，标题只是兜底。**

#### 5.2.4 两种视图（**Canvas 自己的命名法**）

`GradebooksController#show`（`app/controllers/gradebooks_controller.rb#L362`）注释 #L366-L371 原文写明 gradebook "version" 有 `"gradebook"`（默认网格）与 `"individual"`，网格下再分 `"default"` 与 `"learning_mastery"`。
`show_default_gradebook`(#L395) → `render "gradebooks/gradebook"`(#L407)；`show_learning_mastery`(#L430) → `set_learning_mastery_env` + `render "gradebooks/learning_mastery"`(#L435-L436)，需 `outcome_gradebook_enabled?`(#L377/#L387)。学生侧是 `grade_summary`(#L50)。

#### 5.2.5 Canvas 有没有"按科目（跨课程）视图"？—— **我没找到，且所有入口都限定单课程**

**能给出的最强证据**（全文所有入口都以单个 `@context` Course 限定）：
- Gradebook 页：#L363 `authorized_action(@context, @current_user, [:manage_grades, :view_all_grades])`；#L381 `redirect_to polymorphic_url([@context, :gradebook])`。
- Gradebook History：#L300 `.where(context_type: "Course", context_id: @context)`；#L316 `authorized_action(@context, ...)`。
- 在 score / enrollment / gradebook 相关模型里**未见任何 subject / department / 年级聚合概念**。

⚠ **但这属于"未穷举证明"**：**未读 `config/routes.rb`**，也**没有搜索引擎可用**去查 account 级 gradebook / outcome rollup 之类功能 ⇒ 只能写到"**我没找到，且已知入口都限定单课程**"（U12）。

### 5.3 国内同类（仓内既有调研，源：`docs/research/evaluation-rebuild.md:389-471`）

| 产品 | 与本需求相关的结论 | 一手 URL |
|---|---|---|
| **钉钉·宜搭·子表单** | **唯一把「Excel 往返」做进表单的产品**。官方原文：「支持 Excel 批量导入数据（50条/次）」「主表单数据 + 子表单数据一并导出」「导出本地 Excel 后，经数据内容编辑，**子表内容支持重新导回到宜搭表单数据中**」 | <https://docs.aliwork.com/docs/yida_support/wtwabe/up3ftx/in0w72> |
| **飞书·多维表格 Bitable** | 评分字段（1–10 星/心/数字）+ 公式字段（100+ 函数，整列引用 = Excel 的 A:A 语义）+ 仪表盘；OpenAPI 开放文档/记录/字段/视图 + 插件可反向嵌入 | <https://www.feishu.cn/hc/zh-CN/articles/788252329598>、<https://www.feishu.cn/hc/zh-CN/articles/360049067853>、<https://open.feishu.cn/document/server-docs/docs/bitable-v1/bitable-overview.md> |
| **校管家** | 有「自定义评价维度」（适用科目可多选/不限），但**未发现「自定义评估表模板 + 指标权重」**，形态是"送星星打分"，**无 Excel 网格** | <https://helpcenter.xiaogj.com/help-list/detail-113.html>、<https://wiki.xiaogj.com/docs/ping-ce-guan-li> |
| **希沃** | 多层指标体系（一/二级指标 + 点评项）+ 教师自定义 + 管理员审核 + **指标批量导入**；但填报端是**点选送星**，未发现权重 | <https://help.seewo.com/webcube/DC89yqZER5>、<https://help.seewo.com/zp/rwbsCqQKrl>、<https://help.seewo.com/zp/b2AWn4cHrJ> |
| **校管易·易评教** | 「指标模板可配置」「评价总表按需输出」「评课打分随堂录入」 | <https://xiaoguanyi.com/products/easy-teaching-evaluation> |
| **问卷星 / 腾讯问卷 / 问卷网** | 只做到「网格题」（矩阵量表/矩阵评价/自增表格），**列结构由设计者预先固定，填写者不能自由增删列** | <https://www.wjx.cn/help/help.aspx?helpid=160>、<https://cloud.tencent.com/document/product/1304/133322> |

**该次调研的总结论（原文 `:471`）**：「**"真的做成自由单元格 Excel"——国内没有任何一家做成。**」以及「'参数丰富 + 可自定义'在国产产品里的成熟答案 = **维度/指标字典 + 权重占比 + 必评标记**」。

### 5.4 本次独立复核：国内同类「按科目 / 按学生」两个轴（**本轮完成**）

> **取证方式（决定可信度与可复现性）**：本次 **DSH 内置 `web_search` 全程返回 `unparseable response body`（试 6 次全失败）**；Bing / Baidu / DuckDuckGo / Mojeek / SearxNG / Ecosia / Startpage / Brave / Yandex / Google **全部不可用**（死路记录见 §14.7）。
> 全部结论改由 **「直连官方文档站 + 站点 llms.txt 全量语料 + 破解站内搜索 API」** 取得。**未采信任何非一手来源**（知乎 / CSDN / 博客园 / 百度文库全程未作依据）。

#### 5.4.1 结论先行（**本次对外调研最重要的一条**）

> **在能验证到的全部一手来源里，没有任何一家国内同类产品提供以「科目」为一级导航轴的成绩入口。**
> 科目在国内同类产品里的位置**一律是「列」或「筛选条件」，而不是「入口」**；真正的主轴排序是 **按考试批次 ＞ 按班级 ＞ 按表单 / 表格**。

| 产品 | 真正的录入 / 查看主轴 | 「科目」的实际角色 |
|---|---|---|
| 钉钉·宜搭 | **表单**（默认按班级 / 学生组织） | 表单上的一个**下拉选择组件**，官方明写「**科目组件无数据填充功能**」 |
| 钉钉·开放平台 | 班级 / 年级 / 课程 | 只有"创建学科实例"这类主数据维护，**无成绩关联** |
| 飞书（多维表格 / 云文档） | **表格行 / 字段** | 一个**字段（列）** |
| 智学网（科大讯飞） | **考试批次**（账号以准考证号为单位） | 考试内部的一个分析维度 |
| 好分数 | **考试** | 「考试解读」→ 二级页「**学科分析**」 |
| 七天网络 | **考试 / 阅卷批次** | "考试科目"是考试的一个属性 |

**对本项目的直接含义（写进设计文档即符合铁律 0）**：
用户要的「**按科目进入 → 该科目全班成绩单**」在国内同类里**不是"抄一个现成的"，而是差异化能力** —— 与 `edu.grade.history` 变更留痕属同一类（国内主流普遍缺、本仓正好有）。
⇒ 设计文档应写明：「**国内同类以考试批次 / 班级为主轴，按科目入口无先例；本仓自研有据。**」

#### 5.4.2 钉钉：**没有「成绩」这个域**，成绩靠宜搭表单"搭"出来

**证据 A（官方原文）** —— <https://help.dingtalk.io/zh/yida/form/eb291o>：

> 宜搭提供 9 个教育组件，适用于 K12 教育场景，支持选学校、校区、科目等。

9 个组件 = **选学校 / 选校区 / 选科目 / 选学段 / 选学年 / 选学期 / 选年级 / 选班级 / 选学生** —— **清一色是选择器，清单里没有「成绩」或「分数」组件。**
同页给出的官方成绩录入范式（原文）：

> **示例场景：高校奥数竞赛成绩**
> （1）创建一个**普通表单**录入学生成绩，表单上使用**学生、班级、学校、数值**等组件，并且录入对应学生成绩；
> （2）创建**报表**，分别通过以下 2 种方式展示成绩统计……

⇒ **钉钉官方的"成绩录入" = 自建表单 + 数值组件**，粒度**由表单设计决定**（默认一行一学生）；**没有内置成绩簿**。

**证据 B（科目不是主数据轴）** —— <https://help.dingtalk.io/zh/yida/form/dtwzn4>：

> 选科目组件适用于 K12 校园中进行科目选择的应用场景，如兴趣班报名。……**注：科目组件无数据填充功能**
> 数据来源：**每个学段后台对应一套标准学科列表，暂不支持开放修改。**

⇒ 科目是**系统预置枚举**且**不能回填**，只是一个下拉框，**不是能"进入后看到全班成绩单"的一级实体**。

**证据 C（Excel 导入确实有，且支持子表单）** —— <https://help.dingtalk.io/zh/yida/form/andrke>：

> - 支持导入的组件类型：……成员、部门、**数值**、日期、日期区间、**子表单**、关联表单（关联主表）。
> - 普通表单导入数据限制：5000 条，文件大小不超过 **10M**（专属版 50000 条）。
> - ……下载表单数据模板……**支持上传 xsl、xlsx 文件类型**。

⚠ **必须澄清（防止臆造）**：帮助中心只给了**按组件类型**的格式规则，**并没有公布一份带固定列名的导入模板** —— 模板是登录后按你的表单字段**动态生成**的。**报告与设计文档都不得臆造列名。**

**证据 D（负向但极强）** —— 钉钉开放平台 [全量 API 目录](https://open.dingtalk.com/llms-docs/zh-CN/llms-api-catalog.txt)（210,651 字节）关键词命中：**成绩 2 / 分数 0 / 考试 0 / 评分 0 / 成绩单 0** —— 而那 2 次「成绩」全是"数据集**成绩**效记录"（绩效记录，语义无关）。
[教育、课程、班级与直播 API（50 条）](https://open.dingtalk.com/llms-docs/zh-CN/llms-cli-education-live.txt) 覆盖学段 / 年级 / 班级 / 课程 / 学科实例 / 家校架构 / 学生 / 课程参与方 / 直播 / 观看数据 —— **整份清单 0 次「成绩 / 分数 / 考试」**。
⇒ **钉钉开放平台没有任何成绩 / 分数 / 考试接口。**

**留痕**：钉钉帮助中心**全量语料（`help.dingtalk.io/llms-full.txt`，20,979,361 字节 ≈ 21MB）** 中「成绩」命中 **0 次**，全部教育文档均未提及成绩变更审计 / 修改历史 ⇒ **未验证到任何成绩变更留痕能力（证据倾向"不存在"）。**

#### 5.4.3 飞书：成绩是"表格题"，不是"产品域"

用**破解出的站内搜索 API** 逐词统计（`GET https://www.feishu.cn/hc/api/article/search?query=词&limit=10&page=1&offset=0&language=zh-CN`）：

| 查询词 | `total` | 结果性质 |
|---|---|---|
| 成绩 | 137 | **全部**是表格 / 多维表格**公式函数**文档（IFS、MAX、AVERAGE、LOOKUP、PERCENTRANK、AND） |
| 成绩录入 | 71 | **无一条**是「成绩录入」功能文档 |
| 成绩管理 | 102 | 命中的是客户管理 / 项目管理 / **绩效**管理，与教务无关 |
| 成绩分析 | 50 | 泛指 BI 分析（多维表格 AI 问数） |

**唯一的"学生查分"线索** —— <https://www.feishu.cn/hc/zh-CN/articles/401851310424>（原文）：

> 常见使用场景：填写表单后查询已填写信息的状态：**例如查询考试成绩**。

**最有力的一句负向证据** —— <https://www.feishu.cn/hc/zh-CN/articles/360043952834>（官方原文）：

> **通过飞书开放平台，个性化开发和接入校园工具，包括学生选课、成绩查询。**

⇒ **飞书官方自己把「成绩查询」列为需要"通过开放平台个性化开发"的校园工具** —— 即飞书原生没有成绩查询功能。
**矩阵录入**：多维表格在模型上完全能做"学生 × 科目"矩阵（官方文档里 `[成绩]` 就是当作**字段名**在用：`IFS([成绩]=100,"满分",[成绩]>=85,"优秀",...)`），但**没有"成绩矩阵"这个功能名，也没有官方成绩模板**。

#### 5.4.4 学生 / 家长查成绩的入口形态（**"按考试"轴的三条一手证据**）

| 产品 | 一手原文 | 结论 |
|---|---|---|
| **智学网** <https://www.zhixue.com/login.html> | 「温馨提示：**学生用户，用户名和初始密码均为准考证号**；家长用户，请使用注册时的手机号登录。」 | 账号以**准考证号**为凭据 ⇒ 身份天然绑定到**某一次考试** |
| **好分数** <https://www.haofenshu.com/> | 「**考试解读** 考后复习提升，黄金3步法」「**成绩解读：成绩总览、学科分析**即可掌握考试成绩」 | 一级入口是「**考试**」，二级才是「**学科分析**」⇒ **按考试 → 各科** |
| **七天网络** <https://www.7net.cc/build/home/index/index.html> | 「……不受**考试规模、考试类型、考试科目**、答题卡纸张等各种因素限制」「基于学生**日常考试**答题情况，可在手机端查看考试答题情况」 | 业务以**考试（阅卷批次）**为组织单元；**未验证到"按科目 → 历次成绩"入口** |

#### 5.4.5 其余被考察产品

| 产品 | 结论 | 依据 |
|---|---|---|
| **ClassIn / 小鹅通 / 百家云** | **未发现成绩模块**。sitemap 逐条核对：classin.com `page-sitemap.xml`（36 条）+ `post-sitemap.xml`（63 条）无成绩相关页；xiaoe-tech.com（629 条）、baijiayun.com（220 条）同样无 | 三者分别是直播课堂 / 知识付费 / 视频 PaaS，**判断为不提供教务成绩域**（标"未发现"而非"不存在"，未逐页深挖） |
| **校管家（xgj.cn）** | **完全未验证** —— 见 §5.4.6 V1 | — |
| **希沃（seewo）** | **完全未验证** —— 见 §5.4.6 V2 | — |

#### 5.4.6 本次对外调研的**未验证项（逐条写原因）**

| # | 未验证项 | 具体原因（可复现） |
|---|---|---|
| V1 | **校管家（xgj.cn）全部内容** —— "成绩管理在哪一级菜单""Excel 导入模板列名""按学生查历次成绩"三问**全部无法回答** | `www.xgj.cn` / `xgj.cn` / `https://www.xgj.cn/help` **全部 Connection refused（curl 返回 000）**；`help.xgj.cn` **不解析**（`nodename nor servname provided`）。DNS 能解析到 `203.0.113.9` 但 TCP 被拒 ⇒ 判为**该站点对本次网络环境拒绝连接**（疑似仅限国内 IP），**不是"没有该功能"**。**建议换 IP 重跑。** |
| V2 | **希沃成绩录入 / 学情分析** —— **未验证到任何成绩功能名** | `help.seewo.com` 是纯前端 SPA：**无 sitemap.xml / 无 robots.txt / 无 llms.txt（三者均返回 SPA 外壳）**。枚举试过 `/api/search?keyword=成绩`、`/api/v1/search`、`/help/api/search`、`/api/doc/search`、`/api/category/list`、`/api/article/list` —— **全部 404 或同一个 SPA 外壳**；内联 JS 未暴露 API 基址（`Page.chunk.js` 仅 5,572 字节）。`easinote.seewo.com` 全页**无"成绩"字样**；`www.seewo.com` 只有三段解决方案导航。⇒ **报告中不得为希沃编造功能名；需人肉在浏览器里看 SPA，或找其 To B 商务材料** |
| V3 | **飞书 / 钉钉的成绩变更留痕** | 未找到任何成绩修改审计 / 历史版本功能名。**钉钉侧证据倾向"不存在"**（21MB 全量语料"成绩"命中 0） |
| V4 | **智学网 / 好分数 / 七天网络的 Excel 登分模板与留痕** | 三者的登分 / 阅卷都在 **To B 后台**，公开仅能触达登录页与营销页 |
| V5 | **钉钉宜搭"固定列名"的 Excel 导入模板** | **不存在** —— 模板按登录后的表单字段动态生成；公开文档只给按组件类型的格式规则。**切勿臆造列名** |

#### 5.4.7 方法论沉淀（**建议同步进 `docs/research/README.md`**）

**本次没有可用的通用搜索引擎**，有效路径是「**官方站 + 站点 llms.txt 全量语料 + 破解站内搜索 API**」三件套：

1. **`https://help.dingtalk.io/llms-full.txt` ⇒ 20,979,361 字节（≈21MB）钉钉帮助中心全量正文** —— 落地后本地 `grep`，**绕开一切搜索与 403**。`https://help.dingtalk.io/llms.txt` 是站内索引（含中文 `/_llms/zh/product.md`、宜搭 `/_llms/zh/product/tab-4d5724b2.md`）；`https://open.dingtalk.com/llms.txt` 同法可用。
2. **飞书帮助中心站内搜索 API（从页面内联 JS 逆向得到，已验证可用）**：`GET https://www.feishu.cn/hc/api/article/search?query=<关键词>&limit=10&page=1&offset=0&language=zh-CN` ⇒ 返回 JSON（`total` + 列表 + 摘要 highlight）。**可直接当"站点级搜索"用。**
3. **顺序：先 llms.txt → 再站内搜索 API → 最后才考虑通用搜索引擎**（本次通用搜索引擎**全部失败**，见 §14.7）。

### 5.5 对外调研的纠错与**对本仓的直接含义**

#### 5.5.1 本轮**更正**仓内既有假设（3 处，逐条给依据）

| # | 位置 | 既有说法 | 本轮实测 | 依据 |
|---|---|---|---|---|
| **M1** | `docs/research/evaluation-rebuild.md` §4.1 的聚合枚举 | "0 mean / 10 weighted mean / **12 sum / 13 extra credit**" | **12 = `EXTRACREDIT_MEAN`（含额外学分的平均），13 = `SUM`（求和）** —— 12 与 13 的语义**写反了** | `lib/grade/constants.php#L33-L73`：MEAN=0(#L33)、MEDIAN=2、MIN=4、MAX=6、MODE=8、WEIGHTED_MEAN=10、WEIGHTED_MEAN2=11、**EXTRACREDIT_MEAN=12**(#L68)、**SUM=13**(#L73) |
| **M2** | 同处，称 `grade_item.php` 有 `set_aggregation()` / `aggregate_grades()` | — | **`grade_item::set_aggregation()` 不存在**。现版本 = `set_aggregation_fields_for_aggregation($from,$to)`（`grade_item.php#L1609-L1646`，docblock #L1595-L1603 明写"**本方法不落库**"）。**真正的聚合在 `grade_category`**：`aggregate_grades()`(#L605)、`aggregate_values_and_adjust_bounds()`(#L1028)、`aggregate_values()`(#L1504)、`apply_limit_rules()`(#L1781)、入口 `generate_grades()`(#L488) | 同上 |
| **C1** | `evaluation-rebuild.md` §4.2 的 Canvas CSV 描述 | 未写列头格式（本文初稿一度按"常见说法"理解为 `<作业> (<满分>)`） | **作业列头 = `<作业标题> (<作业 id>)`**，**不是满分**：`gradebook_exporter.rb#L164` `assignments.map(&:title_with_id)`，而 `abstract_assignment.rb#L2266-L2274` 的 `title_with_id` = `"#{title} (#{id})"`；**满分单独占一行只读行**（#L238）。导入侧对应地**按列头括号里的 id 匹配**（`gradebook_importer.rb#L529-L544`，正则 `/\A(.*)\s\((\d+)\)\z/`），标题只是 backward-compat 兜底 | `lib/gradebook_exporter.rb#L35-L182`、`app/models/abstract_assignment.rb#L2266-L2295`、`lib/gradebook_importer.rb#L500-L544` |

> ⚠ 本文**不使用**"xlsx/csv 列名"做证据的场合已按上述更正（本仓自身导出用中文字列名，见 `roles.py:2203-2214`，与 Canvas 无关）。

#### 5.5.2 ★ **对本仓最值钱的三条**（直接落到 §7.3 的留痕设计与 §7.1-B 的模型设计）

**(1) Moodle 的 `grade_grades_history` 是"整行快照 + 四要素"，本仓 `edu.grade.history` 应照此加固。**
Moodle 的写入点在**父类** `grade_object` 的 `update()/insert()/delete()` 三处（`grade_object.php#L244-L272 / L341-L366 / L280-L300`），**每一笔写入都追加一条完整字段快照**（不是只存 diff），并自带 `action`（insert/update/delete）+ `source`（`manual/module/import/...`）+ `loggeduser`（"the userid of the person who last modified"）+ `timemodified`（`install.xml#L2187-L2228`）。
⇒ **对本仓的具体含义**：`edu.grade.history` 现有字段 `action`(`create/update/import/copy`) / `source`(`manual/import/copy/system`) / `logged_user_id` / `timemodified` / `old_marks` / `new_marks` —— **四要素已齐**（`registration.py:605-629`），且**比 Moodle 多了 `old_marks` 的显式旧值**。**缺的只有"整行快照"里的其它列**；对新模型 (`edu.grade.line`) 而言，值得**随每条历史冗余存下当时的 `batch_id_at_snapshot` 与 `term_id`**（这样"这次改分发生时他属于哪个班/哪学期"永远可查，正是校长拍板 P5 需要的东西）。
**(2) Canvas 的留痕粒度是"提交版本流水"，可正查/倒查、可按学生或按作业过滤。**
`/api/v1/courses/:course_id/gradebook_history/{days,day_details,submissions,feed}`，`feed` 支持 `ascending` 与按 `assignment_id`/`user_id` 过滤（`gradebook_history_api_controller.rb#L294-L309`）。
⇒ **对本仓的含义**：`/grading/history`（`roles.py:2394-2437`）现在只支持"按 exam + 按 student"两个筛选 + 50 条/页分页。**新成绩簿的留痕页应当做到"按学生 / 按科目 / 按时间"三种可筛**（Moodle 与 Canvas 都有、我们没有第三种）—— 这是**低成本、可对标**的一条。
**(3) 两家的"科目轴"都没有。这条与 §5.4 的国内结论**互相印证**，把"按科目入口"确认为差异化。
- Moodle：`course` 就是科目；grader / user 报表强制单课程（`#index.php` L35/L30），overview 跨课程但**只给"课程 + 总成绩 + 排名"一行**（`overview/lib.php#L184-L267`）⇒ **没有"跨课程 / 按科目"的明细聚合视图**。
- Canvas：所有入口都以单个 `@context` Course 限定（`gradebooks_controller.rb#L363/L381`；`gradebook_history_api_controller.rb#L300/L316`），模型里**未见 subject / department 聚合概念**（但是**未穷举**，见 U12）。
⇒ **结论（写进设计文档即满足铁律 0）**：**"按科目进入 → 该科全班成绩单"在 Moodle / Canvas / 国内同类三边都没有现成先例** ⇒ 本仓自研有据。

#### 5.5.3 本轮对外调研**仍未取到**的项（Canvas / Moodle 侧）

| # | 未取到项 | 具体原因 |
|---|---|---|
| C1 | **Canvas 的建表 DDL**（`db/schema.rb`，以及 `scores`/`submissions`/`versions`/`submission_versions` 的列与索引） | **`db/schema.rb` raw 返回 404** ⇒ §5.2 的 Canvas 存储结论**全部来自模型与控制器源码，不是 DDL** |
| C2 | **Canvas 官方 CSV 导入规范文档 URL** | 未访问 community.canvaslms.com / canvas.instructure.com/doc ⇒ 只有源码级证据（`lib/gradebook_importer.rb`），**无官方文档引用** |
| C3 | **Canvas Gradebook History 的官方文档 URL 与 UI 页面路由** | 文档站未访问；UI 路由需 `config/routes.rb`（未取）⇒ 只有 API 路由 helper 名 |
| M3 | **Moodle 官方文档站（docs.moodle.org）原文** | 未取到 ⇒ §5.1 **全部为 GitHub 源码级证据**（这反而更强，但若报告需引官方文档则需另一轮带浏览器/可访问文档站的环境） |
| M4 | **`grade/grade_letters.php` 与 `grade/edit/letter/edit.php`** | raw **404**。**这不是取回失败**：Moodle 4.5 已无这两个文件 —— 字母逻辑在 `lib/gradelib.php`（读）+ `grade/edit/letter/index.php`（管）；编辑入口是 `index.php?id=<contextid>&edit=1`（#L31/#L46）。**本文初稿曾试图引用 `grade_letters.php`，已更正。** |
| — | **`api.github.com` 中途连接超时** | `curl: (28) Connection timed out after 60001 ms` ⇒ 若干次目录列举失败；但**所有源码文件均经 `raw.githubusercontent.com` HTTP 200 取回落盘**，结论未受影响 |

> **行号可信度声明（引自取证方）**：全部行号来自下载到本地并用 `nl -ba` 编行后阅读的内容，**未凭记忆填写**；Moodle 侧文件均取自同一 commit `89ae02d0007418c50f0911148137f4cb3bd67f4a`；`grade/report/grader/lib.php`、`grade/import/csv/classes/load_data.php`、`lib/grade/grade_item.php`、`app/controllers/gradebook_history_api_controller.rb`、`lib/gradebook_exporter.rb`、`lib/gradebook_importer.rb` 为**完整文件（非截断）**。

---

## 6. 名单事实源：报课现状（**字段级**答案）

> 用户第 4 条口径：「就按照以后学生报课的名单来，谁报课了就知道了」。下面把这句落成字段。

### 6.1 模型与表

| 层 | 模型 | 表 | 文件:行号 |
|---|---|---|---|
| 报课单（意愿） | `op.subject.registration` | `op_subject_registration` | `openeducat_erp/openeducat_core/models/subject_registration.py:25-102` |
| ↳ 必修科目集（m2m） | — | `subject_compulsory_rel`（列 `register_id`, `subject_id`） | `subject_registration.py:37-40` |
| ↳ 选修科目集（m2m） | — | `op_subject_op_subject_registration_rel` | `subject_registration.py:41-42` |
| 门户扩展 | `op.subject.registration`（`_inherit`） | 同表（加 7 列） | `custom_addons/edu_portal/models/registration.py:35-46` |
| **学籍档案（事实）** | `op.student.course` | `op_student_course` | 生产列见 §2.1 实测 |
| **↳ 已选科目（m2m）** | — | **`op_student_course_op_subject_rel`**（列 `op_student_course_id`, `op_subject_id`） | 生产 `pg_class` 实测表名 |

`op.subject.registration` 的**真实列**（生产 `information_schema` 实测，21 列）：
`id, student_id, course_id, batch_id, company_id, create_uid, write_uid, name, state, is_read, is_read_by_parent, create_date, write_date, max_unit_load, min_unit_load, approved_by, applicant_note, reject_reason, doc_type, approved_at, submitted_at`
⇒ **没有任何分数 / 等级 / 学期字段。**

### 6.2 报课路由在哪、现在具备什么能力

全部在 `custom_addons/edu_portal/controllers/enroll.py`：

| 路由 | 行号 | 能力 |
|---|---|---|
| `GET /subject/enroll` | 74-229 | 学生报课目录：课程 → 班级 → 科目池（必修/选修两级 fallback）；**含先修/学分/容量前置校验**（`edu.subject.prereq.edu_precheck`，`:159-161`） |
| `POST /subject/enroll/save` | 230-326 | 建报课单（`doc_type='subject_registration'`），写审计 |
| `GET /student/subjects` | 331-354 | 学生「我的已选科目」：读 `op.student.course.subject_ids` |
| `GET /registrar/subject/approvals` | 359-440 | **教务审批聚合列表**；守卫 `if not fac and not is_priv: → /my/home`（`:362-365`）⇒ **教务可进** |
| `GET /registrar/subject/approvals/<int:rid>` | 441-535 | 审批详情 |
| `POST /registrar/subject/approvals/<int:rid>/set_state` | 536-586 | 通过 / 驳回 |
| `POST /registrar/subject/set_state_bulk` | 587-660 | 批量审批 |

**⇒ 「教务能进的学生名单相关页面」已有先例**：`/registrar/subject/approvals` 用的是 `fac or privileged_staff()` 守卫，而不是 `fac` 单条件。这与 `/grading/entry` 形成对照，也是修 `/grading/*` 门禁的**现成模板**。

### 6.3 学生报课后，名单**存在哪里**（指名道姓的字段级答案）

**两层，答案是第二层：**

**第 1 层 —— 报课单本身（意愿，含科目集）：**

```
op.subject.registration                    （一人一单）
  ├─ compulsory_subject_ids  → subject_compulsory_rel(register_id, subject_id)
  └─ elective_subject_ids    → op_subject_op_subject_registration_rel(op_subject_registration_id, op_subject_id)
```

门户侧并集口径 = `edu_portal/models/registration.py:51-55` 的 `_subject_payload()`（「compulsory ∪ elective，去重升序」）。

**第 2 层 —— 审批通过后落到学籍档案（事实源）：**

> `openeducat_erp/openeducat_core/models/subject_registration.py:64-82` `action_approve()`
> ```python
> course_id = self.env['op.student.course'].search([
>     ('student_id', '=', record.student_id.id),
>     ('course_id', '=', record.course_id.id)], limit=1)
> if course_id:
>     course_id.write({'subject_ids': [[6, 0, list(set(subject_ids))]]})   # ← 整体覆盖
>     record.state = 'approved'
> ```

> `custom_addons/edu_portal/models/registration.py:165-244` `action_enroll_approve()`（门户/后台共用）做同一件事，注释原文：
> 「**注册单 = 最新意愿，档案 `subject_ids` 仍是 LMS/课表读取的事实源**」（`:168-171`）

**⇒ 名单事实源 = `op.student.course.subject_ids`（表 `op_student_course_op_subject_rel`）。**
**「谁报了科目 X」= `op.student.course` 里 `subject_ids` 含 X 的那些行 → 其 `student_id`。**

**而且本仓已经在用它了**（这是本次最重要的"不需要新造轮子"证据）：

> `custom_addons/edu_portal/controllers/lms.py:22-44` `_subjects_for()`
> ```python
> if student:
>     # 个人选课联动：学生视角 = 在读档案 op.student.course.subject_ids
>     # （报课通过后自动出现新科目卡；仅加科目而课程不变也即时联动）。
>     scs = env['op.student.course'].sudo().search([('student_id','=',student.id)])
>     subjects = scs.mapped('subject_ids')
>     return subjects, 'student'
> ```

`/my/courses`、`/my/study`、`/my/study/<subject_id>` **全部**以 `_subjects_for()` 为科目口径。⇒ **「按科目进入」这个入口轴，学生侧已经存在（`/my/study/<subject_id>`）；缺的只是"教务/教师视角 + 名单"那一半。**

**必须点名的两个已知缺口：**

1. **`op.subject.registration` 没有学期字段。** 本仓代码原文承认：
   > `custom_addons/edu_portal/models/registration.py:204-206`「`op.subject.registration` **无学期字段**；`op.academic.term` 无 `is_current`，故用日期覆盖今天判定进行中 term」
   ⇒ **「学生 × 科目 × 学期」这个三元组无法只从报课单得出**，学期必须从 `op.student.course.academic_term_id` 取（生产 `op_academic_term` 2 行：第一学期 / 第二学期）。
2. **`action_enroll_approve()` 是"整体覆盖"语义**（`:221-233` 的 `[(6,0,subject_ids)]`），且带防呆（`:199-203`：payload 为空且档案已有科目时直接 `UserError` 拒绝整体清空）。⇒ **换班/换课会重写 `subject_ids`**，这正是「名单会漂移」的风险源；而本仓已被校长拍板过一条对立面铁律：
   > `tests/smoke/class_change_request.py:773`（**校长拍板 P5**）：「换班后**旧班的已录成绩/考勤**学生仍可见（**历史不能被抹掉**）」
   ⇒ **成绩不能"实时 JOIN 当前 `subject_ids`"来算，必须是存下来的行**（§7.3、§8）。

### 6.4 生产读数（`edu19-prod-db-1`，2026-09-24 09:56 UTC，只读）

| 事实 | 读数 |
|---|---|
| `op_subject_registration` | **1 行**：id=19 / SR0017 / `state=submitted`（**未审批**）/ `doc_type=subject_registration` / `student_id=11`（22B0081 王佐）/ `course_id=16` / `batch_id=13` / `approved_at=NULL` |
| `subject_compulsory_rel` | **21 行** → 科目 id 70,71,73,75,78,80,81,87,90,91,92,99,109,110,111,117,122,123,124,125,138 |
| `op_subject_op_subject_registration_rel` | **0 行** |
| `op_student_course_op_subject_rel` | **2 行**：学生 11（王佐）→ {神论 id=56, 救恩论 id=68}（档案 `batch_id=29` = C·B硕） |
| `op_student_course` | 24 行 / 29 名学生 ⇒ **5 名学生无学籍档案**（id 25/30/39/40/54，名字均为 `【待分配】…`） |

**⚠ 数据自相矛盾处（要在设计里认账）**：那张唯一的报课单指向 `course_id=16 / batch_id=13`，但同一名学生的 `op.student.course` 是 `course_id=20 / batch_id=29`。⇒ **生产上的报课数据是测试数据，不一致，不能当作"报课已经可用"的证据。**

### 6.5 退路：**若报课尚未可用 / 无数据，今天就能录分的名单从哪来？**

用户口径是"以后按报课名单"——**那就必须给出"今天"的可执行方案**，否则整个设计悬空。三条候选，按推荐度排序：

#### 退路 1（**推荐**）：`op.session` 的 (科目 × 班) ∩ 该班学生

**口径**：某科目的名单 = 「该科目在 `op.session` 里出现过的 `batch_id`」∩「`op.student.course.batch_id` 属于这些班的学生」。
依据：`op.session` 有 `subject_id` + `batch_id`（生产 `information_schema` 实测两列都在）。

**我在生产上把它算出来了（可复核，见 §14.3）—— 今天就有 7 组、24 人次：**

| 科目 | 班 | 名单人数 | 学生（学号:姓名） |
|---|---|---|---|
| 圣灵论 | B3 | 6 | 24A0025 万橙 / 24A0026 康有为 / 24A0028 于新 / 24A0029 郑美 / 24A0038 马柠 / 24A0076 苏苏 |
| 希伯来语四 | B3 | 6 | （同上 6 人） |
| 课堂管理 | B3 | 6 | （同上 6 人） |
| 基础信仰 | A1 | 5 | 26A0034 陈雨生 / 26A0035 青青 / 26A0036 李宣雨 / 26A0037 星湉 / 26A0038 艾志恒 |
| 希伯来语二 | B4 | 3 | 23A0133 祁琪 / 23A0135 韩晗 / 23A0139 豆豆 |
| 救恩论 | B1 | 1 | 26A0019 罗中政 |
| 神论 | B1 | 1 | 26A0019 罗中政 |

**风险（必须写清）**：这是一条**推断口径**，不是事实源：
- 生产 `op_session` 只覆盖 5 个班（34/15/13/20/10）；有学生的班 23(A3, 2人)、24(B2, 1人)、28(C·A硕, 2人)、29(C·B硕, 4人) **一节课都没有** ⇒ 这 4 个班的学生**拿不到任何科目名单**。
- **总览班(batch 34) 有 139 节课、覆盖 13 个科目，但 0 名学生** ⇒ 那 13 个科目今天**没有名单**。
- 5 名【待分配】学生**连 `op.student.course` 都没有**。

#### 退路 2：`op.student.course.subject_ids`（与目标口径同源，但今天几乎为空）

今天只有 **1 名学生 × 2 门科目**（王佐 → 神论 / 救恩论）。
**优点**：**与用户要的口径完全一致**，报课一旦跑起来就自动有数据，零迁移。
**缺点**：今天几乎为空，不能单独撑起"今天就能录分"。

#### 退路 3：教务在录入页手工勾选 / 加人（deny-by-default + 白名单）

**形态**：名单默认按退路 1 预填；教务可手工增删此行（增：从全班选；删：标记"本次不评"）。
**优点**：覆盖上面所有边角（无课节的班、总览班科目、待分配学生）；**不需要等报课建好**。
**缺点**：手工名单不可复现，所以**必须存成"名单快照"**（照 `edu.assess.roster` 的形态 —— `assess.py` 的 `EduAssessRoster` 就是这张快照表，`EduAssessTask._build_roster` 只增不覆盖、`EduAssessRoster._roster_subject_uniq` 保证「同一任务里同一被评对象只有一行」。**理由：行的集合必须稳定，否则一次调班会让历史评估凭空少人**。⚠ **本次订正**：这句原引 `assess.py:251-256`，但按 `git show HEAD:` 取回的第 1 期 507 行版本回读，那 6 行是 `EduAssessTask._compute_counts` 的末尾与 `_check_summary_min` 的 def —— **那条引用从写下起就没指向过"名单快照"这件事**）。

#### **推荐组合**：**退路 1 预填 + 退路 3 可编辑 + 名单落成快照；退路 2 作为报课上线后的自动预填口径**

```
预填优先级（写入名单快照时）：
  ① op.student.course.subject_ids 含本科目（= 报课口径，用户要的）
  ② 无 ① 时回落：op.session(subject×batch) ∩ op.student.course.batch_id
  ③ 无 ② 时回落：空名单 + 教务手工加人
落成 = 快照行（student_id, subject_id, term_id, batch_id_at_snapshot）
```

**关键**：快照字段 `batch_id_at_snapshot` 是**校长拍板 P5 的实现手段**（换班不抹历史，§6.3）。

---

## 7. 成绩存在哪 —— 候选与推荐

### 7.1 三个候选

#### (A) 给 `op.subject.registration` 直接加 marks 字段

**形态**：在报课单上加 `marks` / `grade` / `term`。

**否证（4 条，每条都是结构性的）**：

| # | 问题 | 证据 |
|---|---|---|
| A1 | **粒度错**：报课单是「一人一单，单上挂**一组**科目」（m2m），**一行对多科**。要按科存分必须加一个 one2many 行模型 ⇒ **那已经不是"加字段"，而是新建模型**（即 B）。 | `subject_registration.py:37-42`（两个 m2m） |
| A2 | **单据 vs 事实**：报课单是**审批工作流单据**（`draft/submitted/approved/rejected`，`subject_registration.py:43-47`），会被驳回、会被重复提交（生产就有一张未审批的）。**成绩不是单据的状态。** | 同上；`registration.py:199-203` 的防呆逻辑证明这张单还会被"整体覆盖" |
| A3 | **没有学期**：该表**无任何学期字段**（本仓代码原文承认，`registration.py:204-206`）。成绩必须能区分学期。 | 生产 `information_schema` 21 列实测（§6.1） |
| A4 | **历史会被抹掉**：`action_enroll_approve()` 对 `subject_ids` 是 `[(6,0,...)]` **整体覆盖**（`registration.py:221-233`）。若成绩挂在这张单 / 这条档案链上，一次换班 / 换课就可能让历史成绩失去归属 —— 直接违反**校长拍板 P5**。 | `tests/smoke/class_change_request.py:773` |

⇒ **否证成立。**（另注：`op.subject.registration` 对教务有完整 ACL `1,1,1,1`，`openeducat_core/security/ir.model.access.csv:26`；对教师也是 `1,1,1,0`，`:25`——所以问题不在权限，在语义。）

#### (B) 新建 `edu.grade.*`（学生 × 科目 × 学期 × 分数）

**形态**：新模块（或 `edu_portal` 内新模型）承载两层：

```
edu.grade.book    （成绩簿 = 科目 × 学期 × 班/课程；含 state 仅作归档，不作发布门）
   └─ edu.grade.line    （**一行 = 一个学生的本科目总分**）   ← 用户要的"一科一个总分"
          ├─ student_id  (op.student,       required)
          ├─ subject_id  (op.subject,       required)   ← 入口轴之一（按科目）
          ├─ term_id     (op.academic.term, required)
          ├─ batch_id_at_snapshot (op.batch)             ← 校长拍板 P5 的实现手段
          ├─ marks       (Float)                         ← 百分制原始分
          ├─ grade       (Char, compute from marks/pct)  ← 由 op.grade.configuration 映射
          └─ entered_by  (res.users) / write_date        ← "最后修改人 + 时间"
```

**唯一约束**：照 `edu.assess.roster` 的**血泪教训**写 —— 用**非空 Char 键**而不是可空外键：

> `edu_assess/models/assess.py` 的 `EduAssessRoster.subject_ref` 的 `help` 字段（原文）
> 「`subject_ref = fields.Char(string='被评对象键', required=True, index=True, readonly=True, help='非空的唯一键...；**不用可空外键做唯一键 —— Postgres 里 NULL≠NULL，旧两套就栽在这一条上**。')`
> `_roster_subject_uniq = models.Constraint('UNIQUE (task_id, subject_ref)', '同一任务里的同一个被评对象只能有一行名单。')`」

⇒ **`UNIQUE (student_id, subject_id, term_id)` 里的三列都必须 NOT NULL**，否则唯一约束对 NULL 行失效（本仓已有实证：`docs/audit/deprecated-inventory.md:289` 记「`UNIQUE(task_id,item_id,student_id,scorer_id)` 对 `student_id` 为 NULL 的评教行失效」）。

**优点**：粒度正确；有人 / 有时间 / 有留痕位；「一科一个总分」是天然语义；不需要 `op.exam`；即时可见（无 state 门）天然满足。
**代价**：新模型 + 新 ACL + 新 ir.rule + 新页面（但 §7.4 的形态可整抄 `edu_assess`）。

#### (C) 复用 `op.marksheet.line` / `op.result.line`

**为什么不能用（3 条）**：

| # | 问题 | 证据 |
|---|---|---|
| C1 | **结构上绑死 `op.exam`**：`op.result.line.exam_id` 是 `required=True` 且 `ondelete='RESTRICT'`（生产 `pg_constraint` 实测）；`op.marksheet.line` 的百分比 / 等级依赖 `marksheet_reg_id.exam_session_id` 链。**没有 `op.exam` 就没有这一行。** | `openeducat_exam/models/result_line.py:32-35`；`marksheet_line.py:30-50` |
| C2 | **口径是"按 session 混算"**：`_compute_percentage` = 本行所有 `result_line.marks` 之和 ÷ 这些 `exam.total_marks` 之和 × 100（`marksheet_line.py:65-72`）⇒ **一个 session 装多科时，等级是跨科目混算**。 | `marksheet_line.py:65-72` |
| C3 | **该链已被 `UNIQUE(exam_id, student_id)` 锁死**（§3.5），改分不可更新 ⇒ 与用户"录完就能看到"冲突。 | 生产约束实测 |

⇒ **`op.marksheet.line` 只能保留作"历史展示的兼容读取源"，不能作为新成绩的落库目标。**

### 7.2 生产 `edu_assess_*` 实测（作为"形态先例"的证据）

| 表 | 行数 | 说明 |
|---|---|---|
| `edu_assess_template` | 0 | |
| `edu_assess_item` | 0 | |
| `edu_assess_task` | 0 | |
| `edu_assess_task_batch_rel` / `_program_rel` | 0 / 0 | |
| `edu_assess_roster` | 0 | |
| `edu_assess_score` | 0 | |

⚠ **但模块已装**：生产 `ir_module_module` 里 `edu_assess` = `19.0.1.0.0 / installed`。
⚠ **本仓 `docs/code-map.md:38` 说"全部自研 Odoo 模块（9 个 edu_*）"是过时口径** —— 工作区 `custom_addons/*/__manifest__.py` 实际 **13 个**（含 `edu_assess`）。**这个偏差要在设计前修正认知，否则会以为没有先例。**

### 7.3 与既有 `edu.grade.history` 留痕机制怎么衔接

**现状（已完备，不要重造）**：

```python
# custom_addons/edu_portal/models/registration.py:594-662
class EduGradeHistory(models.Model):
    _name = 'edu.grade.history'
    exam_id      = Many2one('op.exam', required=True, ondelete='cascade', index=True)
    student_id   = Many2one('op.student', ondelete='cascade', index=True)
    subject_id   = Many2one('op.subject', related='exam_id.subject_id', store=True)  # ← 科目已冗余
    old_marks / new_marks = Integer
    action  = Selection(create/update/import/copy)
    source  = Selection(manual/import/copy/system)
    logged_user_id = Many2one('res.users', default=uid)
    timemodified = Datetime(default=now)
    note = Char(128)

    @api.model
    def edu_apply_marks(self, att, marks=None, status=None, source='manual', note=None):
        """改分/改状态的唯一入口：写 op.exam.attendees 并留痕。
        返回 'create' / 'update' / ''（无变化）"""
```

**ACL（`views/notice_admin.xml:286-314`）**：教务 `1,1,1,1`（`:286-294`）／教师 `1,0,0,0` 只读（`:296-304`）／系统管理员 `1,1,1,1`（`:306-314`）。**门户一行都没有**（学生看不到留痕）。

**衔接方案（推荐：扩字段 + 加泛化入口，不新建表）**：

| 项 | 做法 | 理由 |
|---|---|---|
| `exam_id` 的强依赖 | `op.exam` 是 `required=True`，新成绩簿没有 exam ⇒ **必须给 `edu.grade.history` 增一个可空泛化定位**（如 `grade_line_id = Many2one('edu.grade.line')`），同时把 `exam_id` 改为可空（`ondelete='set null'`），并加 `@api.constrains` 保证「exam_id 与 grade_line_id **恰有一个**非空」（照 `edu.assess.roster._check_subject` 的写法，见 `assess.py` 的 `EduAssessRoster._check_subject`）。 | 一张留痕表既能装旧成绩也能装新成绩，历史查询页（`/grading/history`）不用分叉 |
| 唯一写入口 | 扩一个 `edu_apply_grade_line(line, marks, source, note)` 兄弟方法，**复用同一张表**与同一份 `action`/`source` 枚举；`edu_apply_marks()` 原样保留（`/grading/*` 还在用） | 「唯一入口」是这套机制的价值所在，**不要开第二张留痕表** |
| 留痕时机 | **每次 `marks` 变化都写一条**（现有语义：`if marks is not None and marks != att.marks` ⇒ 无变化不写，旧值记在 `old_marks`） | 与 `edu.assess.score` 的"幂等更新"不同；**成绩留痕要保留完整修改史**，这是本仓的差异化点（`registration.py:597-600` 原文：「国内三家教务 SaaS 均没有成绩留痕能力……故按差异点做扎实」） |
| 用户第 3 条「不需要发布」的影响 | 无发布态 ⇒ **没有"发布"这个留痕事件**；应把"首次录入 / 修改"两种 `action` 用足，并在页面显式展示"最后修改时间 + 修改人" | 没有发布门，纠错能力就必须由留痕提供 |

### 7.4 与 ACL / ir.rule 怎么衔接（**照 `edu_assess` 抄，不要发明第二套**）

**ACL 形态**（照 `edu_assess/security/ir.model.access.csv:2-16`）：

| 组 | perm | 依据 |
|---|---|---|
| `openeducat_core.group_op_back_office_admin`（教务） | `1,1,1,1` | 教务要能建成绩簿、录分、纠错 |
| `base.group_system` | `1,1,1,1` | |
| `openeducat_core.group_op_faculty`（教师） | `1,1,1,0`（**受行级规则收敛**） | 任课老师能录自己班的 |
| `base.group_portal` / `base.group_user` | **`0,0,0,0`（一行都不给）** | 照 `edu_assess` 口径：门户读侧全走控制器 `sudo()`；不给 RPC 面 |

**ir.rule 形态**（照 `edu_assess/security/security.xml:51-94`，**三条缺一不可**）：

```xml
<!-- ① 教师：收敛到本人任教班 -->
<record id="rule_edu_grade_line_faculty_batch" model="ir.rule">
  <field name="groups" eval="[(4, ref('openeducat_core.group_op_faculty'))]"/>
  <field name="domain_force">[('batch_id_at_snapshot', 'in', user.edu_taught_batch_ids.ids)]</field>
</record>
<!-- ② 教务/系统：恒真域（跨组 OR 的"全放行"分支）—— 缺这条教务会被误收敛成 0 行 -->
<record id="rule_edu_grade_line_admin_all" model="ir.rule">
  <field name="groups" eval="[(4, ref('openeducat_core.group_op_back_office_admin')),
                             (4, ref('base.group_system'))]"/>
  <field name="domain_force">[(1, '=', 1)]</field>
</record>
<!-- ③ 门户：本人（若将来给门户开读权限，行过滤仍在） -->
<record id="rule_edu_grade_line_portal_own" model="ir.rule">
  <field name="groups" eval="[(4, ref('base.group_portal'))]"/>
  <field name="domain_force">[('student_id.user_id', '=', user.id)]</field>
</record>
```

**注意 `user.edu_taught_batch_ids` 的一个已知薄弱处**：`edu_assess/models/assess.py` 的 `ResUsers._compute_edu_taught_batch_ids` 的实现用链①单链（`Faculty.search([('user_id','=',user.id)])`），而本仓**唯一身份反查口径**是 `edu_schedule/models/identity.py`（双向并集，`code-map.md:283-286` 定为硬约定）。新模型若复制这段，**会复制一个已知偏差**；建议改为 `faculty_of_user(env)`（`identity.py:116-118`）或至少注明理由。⚠ 但这属于"顺手修正别人模块"的范畴，**本轮不实施**，只登记。

---

## 8. 两条可行路径对比

> 用户第 1 条口径已**否决 `op.exam` 作为主结构**。本节按队长要求收敛为两条，并把被否的那条作为"反面对照"论证清楚，以免下一个人再提。

### 8.1 路径 ①：**以报课记录为名单、一科一个总分的新成绩簿**（推荐）

**形态**：

```
名单来源   op.student.course.subject_ids（报课口径）→ 回落 op.session(subject×batch) ∩ 班级 → 落成名单快照
存储       edu.grade.line（student × subject × term × marks）—— 一科一行，一行一个总分
入口轴     按科目：/grade/…?subject_id=X   → 该科全部学生的录入网格
           按学生：/grade/…?student_id=Y   → 该生全部科目的录入网格
           两轴是**同一份数据**的两个 WHERE（行=学生 列=科目 vs 行=科目 列=学生），零额外存储
录入人     教务（privileged_staff）+ 任课教师（group_op_faculty，受行级收敛）
可见性     写入即学生可见（无发布态）；学生侧 /grade-book 与 /my/study 读同一份数据
留痕       每次改动写一条 edu.grade.history（§7.3）
评分口径   录百分制原始分 → 由 op.grade.configuration 七档映射出等级（§10）
```

**代价（诚实列全）**：

| # | 代价 | 估量 |
|---|---|---|
| 1 | 新模型 2 个 + 新表（**迁移 0**，生产旧数据 0 行） | 设计 + 实现 |
| 2 | 新 ACL 3 组 + ir.rule 3 条（含**教务恒真域**那条，容易漏） | 照抄 `edu_assess` |
| 3 | 新门户页 2-3 个（教务网格、教师网格、学生视图）+ 1-2 个写路由 | 可照 `/assess/grade/<task_id>` 的矩阵形态（`portal.py:415-487`，`input name="v_<rid>_<iid>"` 命名法） |
| 4 | `edu.grade.history` 要加字段 + 改 `exam_id` 为可空 + 加约束 | 小，但会碰一个**正在被其它逻辑引用**的表（`/grading/*` 六路由 + `/grading/history` 页面）⇒ **必须回归** |
| 5 | 学生侧两处渲染要改（`/grade-book`、`/my/study` 三层） | §9 |
| 6 | 名单预填有 3 个回落分支（§6.5） | 逻辑不多，但**必须落成快照**，否则违反校长拍板 P5 |

**风险**：

| # | 风险 | 缓解 |
|---|---|---|
| R1 | **两套成绩并存**（旧 `op.marksheet.line` 历史 + 新 `edu.grade.line`）导致学生页要合并两个源 | 学生页读侧做**显式合并**并标注来源；旧链冻结不再写入（它本来也已经写不进去了，§3.5） |
| R2 | 名单快照与报课实时数据不一致（教务改报课后名单不同步） | 快照**只在首次建簿时落一次**；提供"按报课刷新名单"按钮（**增量加人，不删已有行**） |
| R3 | 「不需要发布」⇒ 录错即被学生看到 | 靠留痕 + 显式"最后修改人与时间"；**是否要给教师侧一个软性"暂存 / 确认"** 列入拍板问题（§13-Q4） |
| R4 | 教务 ir.rule 恒真域漏写 ⇒ 教务看到 0 行（**最难查的一类 bug，页面 200 但空**） | 验收必须包含"教务账号能看到 N 行"的**正例断言**，不只测教师 |

### 8.2 路径 ②：把 `op.exam` 伪装成"单场考试"硬凑（**否决**）

**形态**：为每个「科目 × 学期」建一个 `op.exam.session` + 一个 `op.exam`（`total_marks=100`），学生作为 attendee，一条 mark = 该科总分，然后按按钮生成 marksheet。

**为什么更差（逐条，全部有一手依据）**：

| # | 问题 | 依据 |
|---|---|---|
| ②-1 | **语义被歪曲，且歪曲到会污染既有报表**。`op.exam` 的第一等公民字段是 `start_time` / `end_time`（**both required**）与 `exam_code`（**required + UNIQUE**）——一个"学期总评"没有考试时间，硬填就是假数据；`op.exam._check_overlapping_times` 还会**拒绝同科目时间重叠**的考试（`exam.py:131-148`），而"一科一个总分"天然只有一条。 | `exam.py:41-45,62-63,131-148` |
| ②-2 | **前置条件链长**：模板约束要求 session 下所有 exam `state='done'`，而 exam 要走 `draft→schedule→held→result_updated→done` 四跳（`exam.py:150-203`）。⇒ 每录一科总分，要先走 4 次状态跃迁。 | `result_template.py:49-55`、`exam.py:150-203` |
| ②-3 | **写一次就锁死**（`UNIQUE(exam_id, student_id)` + 按钮 `invisible state != draft`）⇒ **改分无法反映给学生**。这与用户第 3 条口径正面冲突。 | §3.5 |
| ②-4 | **等级口径是跨科混算**：`_compute_percentage` 的分母是"本 session 下所有 exam 的 `total_marks` 之和"（`marksheet_line.py:65-72`）。若把多科塞进一个 session（为省事），学生看到的等级是**各科混算的假等级**。 | `marksheet_line.py:65-72` |
| ②-5 | **教务仍然进不去**：这条路径要么走门户 `/grading/entry`（`current_faculty()` 挡死，§4.1），要么走后台（`jiaowu-manual.md:152` 的「时间表 / 考试 / 考试参加者 / 结果行」）。**后台那条不代表"两个入口轴"**，只代表"一个能改的表单"：既没有"按科目看全班"，也没有"按学生看全科"，更无法一次录一科整班。 | `roles.py:871-875`、`jiaowu-manual.md:152` |
| ②-6 | **名单只能手工维护**：`op.exam.attendees` 要靠 `wizard/held_exam.py` 或手工加；它**不连报课**（`op.exam.attendees` 只有 `student_id/exam_id/status/marks/room_id/course_id/batch_id`，**无任何选课关联**）。用户要的"按报课名单"完全落不了地。 | `exam_attendees.py:30-47` |
| ②-7 | **每个科目一学期 = 一个 session 的簿记成本**：`op.exam.session.exam_code` 也是 **UNIQUE + required**（`exam_session.py:36-38,65-66`）⇒ 147 门科目 × 每学期 = 几百条"假考试编号"污染 `op.exam`。 | `exam_session.py:36-38,65-66` |
| ②-8 | **已有 186 次写入的实证**：本地库里有人在这条链上改了 186 次分，学生侧数字一次没动（§3.3）。**这不是理论风险，是已发生的失效。** | §3.3 |

**唯一"优点"是假优点**：复用现成表 = 省一次建模。但代价是**把两个语义不同的域（考试事件 / 学期科目总评）压进一张表**，并且要依赖一个**已被证明会静默失效**的桥。

### 8.3 结论

**路径 ① 完胜，且不是"稍好"而是"②不可行"**：②在用户第 1 条（一科一个总分）与第 3 条（录完即见）上**结构性不满足**，第 4 条（报课名单）**完全无法满足**。

### 8.4 附：路径 ③「用 Odoo 内置 spreadsheet / grid」为什么出局

用户需求里"录入"两个字容易引向"类 Excel 表格"。仓内已有调研（`docs/research/evaluation-rebuild.md`）已把这条路走死，直接引用结论，**不重复调研**：

| 载体 | 结论 | 依据 |
|---|---|---|
| `spreadsheet`（社区版，**本库已装**） | **只读**：`o_spreadsheet.js:78149` `isReadonly: () => this.config.mode === "readonly" \|\| this.config.mode === "dashboard"`；编辑动作 `action_edit_dashboard` 属 **OEEL-1**（企业版） | `docs/research/evaluation-rebuild.md:169-182` |
| ↳ 公开分享页 | 学生能看到只读表格，**但下载不了 xlsx**（下载需 `base.group_allow_export`） | 同上 `:184-192` |
| `web_grid`（Grid 视图） | **企业版独占（OEEL-1）**，且官方文档自陈「column cells are hardly configurable and must be numerical」「**only date column fields have been tested**」⇒ 它的"列"是**时间轴**，不是"科目 / 评分维度" ⇒ **方向性错误** | 同上 `:212-220` |
| OCA `spreadsheet_oca` | 19.0 分支存在，但 **AGPL-3.0**（传染性红线） | 同上 `:182`、`:334-341` |
| **能用的那一半（白送的）** | 「**表格 + xlsx 导入 + xlsx 导出**」在社区版**是白送的**（原生列表视图 + `base_import`），只要列表视图不写 `create="false"`；导入菜单条件见 `import_records.js:42-48` | 同上 `:17`、`:238-315` |

⇒ **正确用法**：**不做嵌入式电子表格，而是「门户矩阵页（HTML table + input）+ 后台可编辑列表 + xlsx 往返」三面共用一份数据**。这正是 `edu_assess` 已落地的形态（`evaluation-rebuild-design.md:257-265` 的三面表）。**本仓已有先例，零新机制。**

---

## 9. 学生"立刻看到"的渲染路径怎么改

### 9.1 `/grade-book`（`controllers/batch2.py:1034-1093`）

**现状**：只取 `current_student()`，无参数，读 `op.marksheet.line`。

**改造点（三处，都很小）**：

| # | 改动 | 说明 |
|---|---|---|
| 1 | **加"代看"能力**：允许 `?student_id=<id>`，但**仅当 `privileged_staff()` 或该生属于本人任教班**时接受；否则忽略参数回落本人 | 这就是入口轴 (b) 的"按学生"。**必须显式判空**，不能只靠参数存在与否（本仓已有前例：`_teacher_exam(id)` 越权按不存在处理，`roles.py:857-869`） |
| 2 | **数据源合并**：先读新表 `edu.grade.line`（按科目，一行一总分），再叠加读 `op.marksheet.line`（历史，标记为"历史成绩单"） | 两个源显式分区渲染，**不混算**（旧源是跨科混算口径，见 §7.1-C2） |
| 3 | **教务视角的落点**：教务进来不再是"仅面向学生账号"告警，而是"选学生"或"选科目"入口 | 模板 `views/batch2.xml:40-45` 的 `t-if="not student"` 分支要改写为按角色的两态 |

**保留不动**：`/grade-book/report/download`（`batch2.py:1095-1126`）与 `/users/result-overview`（`batch3.py:890-916`）在改造后仍需能读到旧数据，否则历史成绩丢失（违反校长拍板 P5 的精神）。

### 9.2 `/my/study` 成绩三层（`docs/plans/study-hub-v3-design.md` §3）

**该设计文档 §3.2 的数据流原文（`:151`）**：

> `└─ 档案成绩三层：op.marksheet.line / op.result.line / op.exam`

**三层结构（`study.py:163-168` 的 docstring）**：L1 本学期总览（每科目 得分/满分/及格线/加权占比/班级区间）／L2 科目条目（单次考试）／L3 单条目反馈（考试备注）。

**改造点**：

| # | 改动 | 关键 |
|---|---|---|
| 1 | `_grade_layers()`（`study.py:163-239`）的**取数层**改为先读 `edu.grade.line`，`op.marksheet.line` 作历史 | **L1 的"一科一行"语义与新模型天然吻合** —— 现在的 L1 是用 `build()` 把多场考试按 `subject_id` **聚合出来**的（`study.py:186-216` 手工累加 `got`/`total`/`pass_line`），新模型下 L1 是**直接读一行**，逻辑反而简化 |
| 2 | `_exam_class_range()`（`study.py:151-160`）现在读 `op.result.line` 算 班级 min/max/avg ⇒ 要新增一个读 `edu.grade.line` 的同功能函数 | 这是学生端唯一"横向比较"功能，**不能因为换源就消失** |
| 3 | `_sem_key()`（`study.py:220-228`）的"历史学期折叠"逻辑：新模型**自带 `term_id`** ⇒ 分组不再需要按登记册 / 年份兜底（那正是 `marksheet_reg_id` 为空导致的缺陷） | 新模型顺手消掉一个既存缺陷 |
| 4 | 模板 `views/study.xml:180-215` 的渲染字段 | L1/L2/L3 的字段名要同步 |
| 5 | `my_study()` 里的课程卡（`study.py:287-309`）现在靠 `grades['current']` 里对 `subject` 名做**字符串匹配**取 `pct`（`:291-294`）⇒ 换源后要改成按 `subject_id` 匹配 | 字符串匹配同名科目会串（生产就有「神论」同时出现在 B1 与总览班） |

**"立刻看到"的成本**：`/my/study` 与 `/grade-book` 的学生读侧**全部走 `sudo()`**（§4.3），所以**没有 ACL 需要动**；"立刻" = 无 state 门 = 零额外工作。**这是路径 ① 相比 ② 最省的一环。**

### 9.3 兼容策略（防止历史成绩消失）

```
学生成绩页（多个源，显式分区，不混算）：
  ① edu.grade.line     「本科目成绩」（新，一科一总分）
  ② op.marksheet.line  「历史成绩单」（旧，按登记册/学期折叠，只读）
  ③ /users/result-overview  继续读 ②（本轮不改口径，避免影响既有断言）
迁移：不迁移旧数据（生产旧数据为 0 行 —— op_marksheet_line = 0，无迁移成本）
```

**⚠ 但本地克隆库有旧数据**（`op_marksheet_line` = 1、`op_result_line` = 1，2026-09-24 09:53 UTC）：本地演示环境需要保留 ② 的读取路径，否则演示页会从"有成绩"变成"无记录"，是**演示回归**而非真回归。

---

## 10. 「总成绩」的评分口径：录百分制自动映射等级 / 直接选等级 / 并存

### 10.1 现状资产（已配置，可直接用）

生产 `op.grade.configuration` **7 行**（2026-09-24 实测）：

| id | `min_per` | `max_per` | `result` |
|---|---|---|---|
| 8 | 90 | 100 | A+ |
| 9 | 80 | 89 | A |
| 10 | 70 | 79 | B |
| 11 | 60 | 69 | C |
| 12 | 50 | 59 | D |
| 13 | 40 | 49 | E |
| 14 | 0 | 39 | F |

模型：`openeducat_erp/openeducat_exam/models/grade_configuration.py:24-40`，字段 `min_per` / `max_per` / `result`（`_rec_name = "result"`），约束 `max_per ≤ 100` 且 `min_per ≤ max_per`。
**生产 `op_grade_configuration_op_result_template_rel` = 0 行** —— 也就是说**这份七档配置目前挂在任何 `op.result.template` 上都没有**（因为 `op_result_template` = 0）。它是**配置就绪但从未启用**的状态。

### 10.2 基座现成的映射实现（可抄口径，不可直接复用代码）

```python
# openeducat_erp/openeducat_exam/models/marksheet_line.py:74-87
@api.depends('percentage')
def _compute_grade(self):
    for record in self:
        if record.evaluation_type == 'grade':
            grades = record.marksheet_reg_id.result_template_id.grade_ids
            for grade in grades:
                if grade.min_per <= record.percentage and grade.max_per >= record.percentage:
                    record.grade = grade.result
                    break
                else:
                    record.grade = None
        else:
            record.grade = None
```

⚠ **同时存在一处口径不一致（要在新实现里避开）**：`op.result.line._compute_grade`（`result_line.py:55-71`）拿 **`record.marks`（原始分）** 去比 **`min_per`/`max_per`（百分比阈值）**，而 `op.marksheet.line._compute_grade` 拿 **`record.percentage`**。**同一份七档配置，两处不同口径。**

### 10.3 三选一分析

| 方案 | 形态 | 评价 |
|---|---|---|
| **(甲) 只录百分制，等级自动算** | 用户只填 0-100，`grade` 是 `compute`（照 `marksheet_line.py:74-87` 的口径，用 `pct` 与阈值比） | **推荐**。理由：① 七档已配置好，零新增配置；② 单一数据源（`marks`），等级永不与分数矛盾；③ 教务 / 教师录入只需填一个数，最快；④ 与 `op.grade.configuration` 现有语义 1:1 对齐 |
| **(乙) 只选等级，分数自动算** | 用户选 A/B/C… | **不推荐**。等级→分数是**一对多**（A = 80~89 任一分），会丢掉真实分数；学生端 `_exam_class_range`（班级 min/max/avg，`study.py:151-160`）失去意义 |
| **(丙) 两者并存（可覆盖）** | 录百分制自动映射等级，同时允许教务手工覆盖 `grade` | **作为 (甲) 的可选增强登记**，不作为首版。理由：① 引入"分数与等级可能不一致"的状态，需要额外的审计语义（留痕表要同时记两列）；② 本仓**暂无对"等级与分数必须一致"的需求来源**（`op.grade.configuration` 是纯粹的全院统一标准表，没有任何"个别课程例外"的配置位）；③ 若将来需要，实现位就是 `grade` 从 `compute` 改成 `compute + store + inverse` |

### 10.4 设计建议（写给设计文档）

1. **`edu.grade.line.marks` 用 `Float` 还是 `Integer`？** 建议 **`Float`**（保留小数），但 `op.grade.configuration` 的阈值是 `Integer`（`grade_configuration.py:29-30`）⇒ **比较时统一到"百分比"语义**：`pct = marks / book.max_marks * 100`，再与 `min_per`/`max_per` 比。**必须显式写明这一点**，否则会重演 §10.2 的口径分裂（`op.result.line` 的 bug）。
2. **等级字典用 `op.grade.configuration`，但不要走 `op.result.template`**：七档表本身是干净的独立字典（它上面没有 `exam_session_id` 之类的外键），**可以直接引用**；但**不要**为了用它而建 `op.result.template`（那会把 §3 的锁死机制一起引进来）。
3. **"满分"必须显式存**：`edu.grade.book.max_marks`（默认 100）。`op.exam.total_marks` 是这层的先例（`exam.py:54`），但一科一个总分时它属于**成绩簿**级而不是"考试"级。
4. **映射函数只写一处**：建议做成模型方法（如 `edu.grade.book.grade_of(pct)`）而不是 `compute` 里的内联循环，避免本仓已经犯过的"三处实现三个口径"。

---

## 11. 推荐 + 为什么

### 11.1 推荐

> **新建「成绩簿」域（`edu.grade.book` / `edu.grade.line`），名单以 `op.student.course.subject_ids`（报课）为首选口径、以 `op.session`(subject×batch) ∩ 班级 为今日回落、**落成名单快照**；一科一行一个总分；录百分制、按 `op.grade.configuration` 七档自动映射等级；教务与任课教师双角色可录，写入即学生可见；每次改动写 `edu.grade.history`。形态整抄 `edu_assess` 的三层与安全模型。**

### 11.2 为什么（六条理由，逐条回指上文）

1. **它正面满足用户四条口径，且不与任何一条冲突**：一科一个总分（§7.1-B 粒度正确）／教务+老师（§7.4 ACL）／录完即见（无 state 门）／报课名单（§6.3 事实源已存在）。
2. **它不需要发明任何新机制**：矩阵录入抄 `/assess/grade/<task_id>`（`portal.py:415-487`）；名单快照抄 `edu.assess.roster`（`assess.py` 的 `EduAssessRoster` 整类 + 唯一键 `EduAssessRoster._roster_subject_uniq`，含"非空 Char 唯一键"的血泪教训 —— 原文在 `EduAssessRoster.subject_ref` 的 `help` 里）；ACL/ir.rule 抄 `edu_assess/security/`（含**教务恒真域**这条关键规则）；xlsx 往返用社区版白送的 `base_import` + `/web/export/xlsx`；留痕复用 `edu.grade.history`。**"能抄不造"在四层上全部成立。**
3. **它是唯一能让"按科目 / 按学生"两个轴都成立的方案**：两轴只是同一份数据（学生 × 科目 × 分数）的两个 WHERE。而 `op.exam` 路径的两个轴都要靠"建不同的 session 再筛"来伪造（§8.2-5）。
4. **它顺手消掉两个既存缺陷**：① 学生页的"历史学期折叠"不再需要 `marksheet_reg_id` 为空时的年份兜底（`study.py:220-228`）；② `_grade_layers()` 的 L1 从"控制器里手工聚合多场考试"变成"直接读一行"（§9.2）。
5. **它在风险上是最小的**：不碰 `op.exam`（基座只读原则，`code-map.md:39`）；不回填历史（生产旧数据 0 行，**零迁移**）；不改学生侧的 ACL（读侧全 `sudo()`，§4.3）；新表新模块，**可以独立回滚**（`code-map.md:303` 的 `safe_upgrade.sh` 口径：新模块首装用 `-i`，回退 = 卸模块 + 删表，不影响任何既有数据）。
6. **它做的是一件国内同类没做成的事（差异化，不是抄）**：「**按科目**」这条轴在国内同类里**没有先例** —— 钉钉宜搭的 9 个教育组件里没有成绩 / 分数组件，飞书官方把「成绩查询」列为需开放平台二次开发的能力，智学网 / 好分数 / 七天网络一律以**考试批次**为主轴，科目只是"列"或"筛选条件"（完整证据 §5.4）。⇒ 这一点**必须写进设计文档**，既满足铁律 0 的「无先例方能自研」，也让这条能力在对外叙事上站得住（与已有的 `edu.grade.history` 变更留痕同属"国内主流缺、本仓有"）。

### 11.3 明确不做

| 不做 | 理由 |
|---|---|
| 把 `op.exam` 当主结构 | §8.2 八条否证 |
| 给 `op.subject.registration` 加 marks 字段 | §7.1-A 四条否证 |
| 复用 `op.marksheet.line` 作落库目标 | §7.1-C 三条否证（`exam_id` required + 跨科混算 + 唯一约束锁死） |
| 嵌入式电子表格（`spreadsheet` / `web_grid` / Univer / Handsontable） | §8.4；社区版只读、企业版独占、OCA 是 AGPL、Handsontable 7.0 起非开源 |
| 新开第二张留痕表 | `edu.grade.history` 已完备且是差异化点，扩字段即可（§7.3） |
| 引入"发布 / 草稿"态 | 用户第 3 条明确"不需要发布" |
| 改动 `edu_brand` 或请假相关文件 | 并行代理正在改（工作区纪律） |

---

## 12. 未验证清单（逐条写原因）

| # | 未验证项 | 原因 |
|---|---|---|
| U1 | **教务账号在生产上打开 `https://edu.example.org/grade-book` 的实况** | 无教务账号凭据，无法做登录态实测。本文对该页结论来自**代码级推演**（`batch2.py:1036` 无参数 + `views/batch2.xml:40-45` 的 `not student` 分支）与队长转达的实测。**建议由能登录的人补一张截图**。 |
| U2 | **教务账号在生产上打开 `/grading/entry` 的 HTTP 状态** | 同上（无凭据）。结论来自 `roles.py:873-875` 源码 + 生产 `op_faculty` 读数 + Odoo `active_test` 源码三重推演，**逻辑闭合但非端到端实测**。 |
| U3 | **本地克隆库 `edu_grade_history` 的 186 条是否为另一代理的测试产物（而非"人"的改动）** | 读数是事实（`exam_id=11, student_id=5, n=186, source ∈ {backend, manual}`），**改动的发起者未验证**。但**结论不依赖发起者** —— 不论谁改的，`op.exam.attendees.marks=20` 与 `op.result.line.marks=92` 的**数值不一致本身**就是断层的证据。 |
| U4 | **`op_marksheet_line.marksheet_reg_id = NULL` 那行的确切来源** | 与 `scripts/seed_yongyue_data.py:379-391` 的写法吻合（直接 create，不带 register），但**未逐字比对脚本输出**，故只能说"高度吻合"。 |
| U5 | **`op.session` 的 139 节"总览班"课节的业务含义** | 只知事实（batch 34 = 总览班、0 学生、139 节课、覆盖 13 科）。**它是不是排课工具生成的"汇总视图班"未验证**（未读 `edu_schedule` 的建课逻辑）。这直接影响 §6.5 退路 1 的覆盖度判断。 |
| U6 | **`op.subject`（147 门）与 `op.batch`（12 个）的对应关系是否完备** | 只在 `op_session` 层做了 (subject × batch) 推断；`edu_course_subject`（478 行，专业 × 科目 × 必修/选修）**未展开验证**，它可能是比 `op.session` 更好的退路 1 数据源。 |
| U7 | **`edu_assess` 的三个 `edu_assess_task_*_rel` 表与 `edu.course.subject` 的关系** | 未展开（本题不需要）。 |
| U8 | **本地克隆库 `op_subject_registration` = 12 行、`op_student_course_op_subject_rel` = 43 行** —— 本地报课数据比生产丰富得多，**本地实测结论能否类推生产** | 生产读数已单列（§6.4）；本文所有"生产"数字均标注来源与时刻，不混用本地。 |
| U9 | **`edu_taught_batch_ids` 用单链反查是否已在别处被认定为缺陷** | 本文只指出它偏离 `identity.py` 的硬约定（`code-map.md:283-286`），**未核实是否已有审计记录**。 |
| U10 | ~~Moodle `grade_items` / `grade_grades` / `grade_letters` / `grade_categories` 的真实表结构~~ | ✅ **本轮已解决**（`MOODLE_405_STABLE` @ `89ae02d0007418c50f0911148137f4cb3bd67f4a`）：`itemtype` 真实枚举 **4 值**（mod/manual/category/course）、`grade_grades` 的 `userid-itemid` 是**数据库硬唯一约束**、`grade_letters` **纯显示**（3 条证据）。详见 **§5.1.1–§5.1.3**。**未取到**：Moodle 官方文档站原文（`grade/grade_letters.php` 与 `grade/edit/letter/edit.php` **在 4.5 已不存在，raw 404** —— 是"文件没了"不是"取不到"）。 |
| U11 | ~~Canvas `gradebook_history`（成绩变更留痕）的存在与字段~~ | ✅ **本轮已解决**：**存在**，是"提交版本流水"，4 个端点 `/api/v1/courses/:course_id/gradebook_history/{days,day_details,submissions,feed}`；字段含 `grader_id`/`graded_at`/`new_grade`/`current_grade` → **谁/何时/改成什么三要素齐全**。详见 **§5.2.1**。**未取到**：官方文档 URL 与 UI 页面路由（需 `config/routes.rb`）。 |
| U12 | ~~Canvas 是否有"按科目（跨课程）视图"~~ | ⚠ **本轮"仍未穷举"**：**未找到，且已知入口全部以单个 Course `@context` 限定**（`gradebooks_controller.rb#L363/L381`、`gradebook_history_api_controller.rb#L300/L316`），模型里未见 subject/department 聚合概念。但 **`config/routes.rb` 未取到 + 无搜索引擎** ⇒ 只能写到"没找到"，**不是确定性否定**（§5.2.5）。 |
| U21 | **Canvas 的建表 DDL**（`db/schema.rb` 与 `scores`/`submissions`/`versions`/`submission_versions` 的列与索引） | **未取到**：`db/schema.rb` raw **404**。⇒ §5.2 的 Canvas 存储结论**全部来自模型与控制器源码，不是 DDL**。 |
| U22 | **Canvas 官方 CSV 导入规范文档 URL；Gradebook History 的官方文档 URL 与 UI 路由** | **未取到**：文档站未访问（按指令不做站点检索）；UI 路由需 `config/routes.rb`（未取）。⇒ 这两条只有**源码级证据**，无官方文档引用。 |
| U14 | ~~钉钉 / 飞书是否有独立的「成绩管理」产品~~ | ✅ **本轮已解决**：**都没有**。钉钉宜搭的 9 个教育组件里**没有成绩 / 分数组件**，开放平台全量 API 目录"成绩"仅 2 次命中且全是绩效记录、"考试 / 评分 / 成绩单"为 **0**；飞书官方把「成绩查询」列为需**通过开放平台个性化开发**的校园工具。证据见 **§5.4.2 / §5.4.3**。 |
| U19 | **校管家（xgj.cn）与希沃（seewo）的成绩功能** | **未验证（本轮已尽力，原因具体）**：校管家 4 个 URL 全部 **Connection refused（curl 000）**，`help.xgj.cn` 不解析 ⇒ 疑仅限国内 IP，**建议换 IP 重跑**；希沃 `help.seewo.com` 是**纯前端 SPA**，无 sitemap / robots / llms.txt，6 条 API 猜测路径全 404，内联 JS 未暴露 API 基址 ⇒ **需人肉在浏览器里看**。详见 §5.4.6 V1 / V2。 |
| U20 | **飞书 / 钉钉 / 智学网 / 好分数 / 七天网络的成绩变更留痕** | **未验证**。钉钉侧证据倾向**不存在**（21MB 全量帮助语料中"成绩"命中 0）；其余三家的登分后台对公众不可达。详见 §5.4.6 V3 / V4。 |
| U15 | **希沃某条 URL 的拼写** | 仓内既有调研给的是 `https://help.seewo.com/zp/rwbsCqQKrl`（本文 §5.3 已按原文列出）。**本次未重新访问验证**。 |
| U16 | **`edu.grade.history.exam_id` 改为可空后，`/grading/history` 页面与六个 `/grading/*` 路由的回归范围** | 属实施期问题，本文只登记风险（§8.1-代价 4），**未做回归清单**。 |
| U17 | **`op_academic_term`（第一学期 / 第二学期）与实际学年 `op_academic_year` 的对应与期间字段** | 只读了两行的名字，**未验证 term ↔ year 的起止日期字段**，而学期维度是新成绩簿的必需键。 |
| U18 | **列名类型并存（`op_batch.name` 是 varchar、`op_course.name` 是 jsonb）是否是全库普遍现象** | 本次只发现了这一处，**未做全库列类型普查**；写 SQL 时逐个 `information_schema` 核对仍是必需动作（§14.3）。 |

---

## 13. 需要用户拍板的问题清单

> 这些是"设计前必须知道答案，否则会做错方向"的问题。**每条都给了我的倾向**，用户可以直接说"按你的"。

| # | 问题 | 为什么必须问 | 我的倾向 |
|---|---|---|---|
| **Q1** | **成绩的"官方来源"认哪一层？** (a) 教务在后台手工录入为准；(b) 任课老师录、教务只审；(c) 两者都录、都可以改（谁后改谁生效，靠留痕追责）。 | 用户说"教务系统老师可以录入"，**但没说是"都能改"还是"分开录"**。这决定 ACL、决定教师能不能改教务录过的分、决定要不要"锁定"概念 | **(c) 都能改 + 留痕**。理由：用户第 3 条说"不需要发布"，说明不想引入流程态；留痕已完备，能追责就不必靠流程防错 |
| **Q2** | **教师能录的范围**：只限「自己任教该科目**且**该班」，还是「自己任教的科目，所有班」？ | 决定 ir.rule 的收敛键是 (batch, subject) 还是 subject。生产现状是**216 节课全挂在同一个「待定」教师名下** ⇒ 若不按 (batch, subject) 收，一个老师将能改全校 | **按「本人任教该科目且该班」双重收敛**（= `op.session` 的 faculty_id × subject_id × batch_id 三元组）。这与 `_teacher_exam_domain()`（`roles.py:842-855`）的粒度一致 |
| **Q3** | **名单的最终口径**：(a) 只认报课（`subject_ids`）—— 严格照用户原话；(b) 报课为主 + 教务可手工加人（用于"没报课但来上课"的补录）；(c) 只认班（`op.session` 的 subject × batch）。 | 生产报课数据几乎为空（1 张未审批的单），**(a) 今天录不了分**；但 (b) 会不会与用户"按报课名单"的意图冲突，只有用户能定 | **(b)**。理由：用户说"就按照以后学生报课的名单来，谁报课了就知道了"—— 这是他心里**名单的主要来源**，不是"禁止教务加人"；而 §6.5 证明纯 (a) 今天不可执行 |
| **Q4** | **教师录分要不要一个"我这一栏填完了"的动作？** 用户说"不需要发布"，但"发布"和"我填完了"是两件事。 | 无发布态 ⇒ 教师填一半被学生看到是必然的。**这会不会是问题，只有用户知道** | **先不做**。理由：用户明确说"不需要发布"；且班级规模（生产最大的班 6 人）意味着"填一半"的时间窗极短。但**登记为已知取舍** |
| **Q5** | **"一科一个总分"的评分制**：见 §10。倾向 (甲) 录百分制自动映射七档，还是 (丙) 允许教务 / 老师手工覆盖等级？ | 只有用户知道学院有没有"个别课程不按 90/80/70… 分级"的情形 | **(甲)**；(丙) 作为可选的后续增强 |
| **Q6** | **成绩的粒度是"每学期每科一行"，还是"每学期每科可有多次（如期中 / 期末各一行，总分另算）"？** | 用户原话说"一科的**总成绩**"—— 听起来是一行。但学院可能有期中 / 期末两场。这不问清楚，模型会做错 | **一学期一科一行（用户原话直译）**。若要多次，则一行改成"一条成绩记录 + 一个汇总字段"，**属于 v2** |
| **Q7** | **旧成绩怎么处理？** 新成绩簿上线后，学生页是否要**同时**显示旧的 `op.marksheet.line` 历史（生产 0 行，但本地 / 未来可能有）？ | 决定 §9.3 的兼容层要做多厚 | **保留只读展示、显式分区**（生产 0 行 ⇒ 实际成本近零，但本地演示环境需要它） |
| **Q8** | **「待分配」学生（5 名，无 `op.student.course`）与「总览班」的 13 门科目（0 学生）要不要能录分？** | 这是"今天录分"会立刻撞到的边角。要么限定"只有报了课 / 有班的能录"，要么允许手工加人 | **允许教务手工加人**（即 Q3 选 (b) 的一个具体后果），否则这 5 名学生**永远无法出现在任何成绩单上** |
| **Q9** | **这次做多大？** (a) 只做教务 / 教师录入 + 学生只看（最小闭环）；(b) 加 xlsx 批量导入导出；(c) 加班级区间 / 排名 / 及格率统计；(d) 加成绩单 PDF。 | 决定分几期、每期交付面 | **(a) + (b)**（用户原话只到"录入"和"看到"，但 xlsx 是社区版白送的、且班级 6 人规模下教务很可能手上有 Excel）；(c)(d) 留后 |
| **Q10** | **教务的入口放哪？** (a) 门户新页（`/grade/…`，与 `/grading/*` 并列）；(b) 后台菜单（照现行设计哲学 `jiaowu-manual.md:173` "教务的入口在后台"）；(c) 两者都要。 | 用户原话是"**我正在使用教务权限进入这个页面：/grade-book**"—— 他明确想走**门户**，这与现行设计哲学（教务走后台）**冲突**。只有用户能定 | **(a) 门户**，理由是用户原话；但**同时把"按科目"的入口也挂到后台菜单**（后台是教务已熟悉的通道，且不增加门户职责） |

---

## 14. 附录：取证命令与死路记录

### 14.1 基座源码快照与容器一致性对拍（**先做这一步，否则行号不可信**）

```bash
# 容器内
docker exec edu19-clone-web-1 sh -c 'md5sum /mnt/extra-addons/openeducat_exam/models/*.py'
# 工作区（逐个文件对拍；下面是一条命令，` 只是换行转义）
md5 -q openeducat_erp/openeducat_exam/models/exam.py openeducat_erp/openeducat_exam/models/exam_session.py openeducat_erp/openeducat_exam/models/exam_attendees.py openeducat_erp/openeducat_exam/models/marksheet_register.py openeducat_erp/openeducat_exam/models/marksheet_line.py openeducat_erp/openeducat_exam/models/result_line.py openeducat_erp/openeducat_exam/models/result_template.py openeducat_erp/openeducat_exam/models/grade_configuration.py
```

**结果：八个文件 MD5 逐一相同** ⇒ **本文引用的 `openeducat_erp/` 行号 = 本地容器里真正跑着的源码**。
> 这解决了本仓的一个已知陷阱：`code-map.md:48-58` 明确警告"源码快照 ≠ 生产 schema"，并给了一条 2026-09-24 的翻车先例。**本文所有"表 / 列 / 约束"类断言一律以生产 `information_schema` / `pg_constraint` 实测为准，不以快照为准。**

### 14.2 生产只读取证（**铁律：只 SELECT，不建临时表，不做任何写操作**）

```bash
ssh -o BatchMode=yes -o ConnectTimeout=25 prod-host 'docker exec -i edu19-prod-db-1 psql -U odoo -d edu19 -A -P pager=off' <<'SQL'
SELECT now() AS prod_reading_at;
SELECT 'op_exam' AS t, count(*) AS n FROM op_exam
UNION ALL SELECT 'op_exam_session', count(*) FROM op_exam_session
...
SQL
```

- SSH 偶发超时 ⇒ **重试即可**（本次重试 2 次后成功）。
- ⚠ 首次连接会打印 `Warning: Permanently added '203.0.113.10' (ED25519) to the list of known hosts.` 到 **stderr** —— 那是正常的，**不是失败**，退出码为 0。
- ⚠ **多行 SQL 必须用 heredoc**，不要用 `-c "..."` 内联：psql 的单行内联会被外层 shell 先吃一层引号，本次实际踩到过一次（`ERROR: column "op_exam.*" must appear in the GROUP BY clause` —— 那是 `AS t` 被 shell 吞掉后的假错误）。

### 14.3 生产名单推算（§6.5 退路 1 的可复现命令）

```sql
SELECT s.name::text AS subject, b.name::text AS batch, count(sc.id) AS roster_n,
       string_agg(st.gr_no || ':' || rp.name, ', ' ORDER BY sc.student_id) AS students
FROM (SELECT DISTINCT subject_id, batch_id FROM op_session) x
JOIN op_subject s ON s.id = x.subject_id
JOIN op_batch   b ON b.id = x.batch_id
LEFT JOIN op_student_course sc ON sc.batch_id = x.batch_id
LEFT JOIN op_student        st ON st.id = sc.student_id
LEFT JOIN res_partner       rp ON rp.id = st.partner_id
GROUP BY 1, 2 HAVING count(sc.id) > 0 ORDER BY 3 DESC, 1;
```

> ⚠ **本仓列名陷阱（会浪费半小时）**：
> - `op_student` **没有 `name` 列**（`_inherits` `res.partner`）⇒ 必须 `JOIN res_partner`。
> - `op_faculty` **没有 `name` 列**，也**没有 `user_id` 列**（`user_id` 经 `_inherits` 来自 `res_partner.user_id`）。
> - `op_batch.name` 是 **`character varying`**（不能 `->>'zh_CN'`），而 `op_course.name` 是 **`jsonb`**（能）。**同一个库里两种形态并存。**
> - `op_marksheet_line` **没有 `grade` 列**（它是 `compute` 不 `store`，`marksheet_line.py:46`）—— 想 SELECT 它会报 `column "grade" does not exist`。

### 14.4 本地克隆库取证（**只读；该库有其它代理在并发改动，读数必须带时刻**）

```bash
docker exec -i edu19-clone-db-1 psql -U odoo -d edu19 -A -P pager=off <<'SQL'
SELECT now() AS reading_at;   -- 2026-09-24 09:53:57.553929+00
SELECT * FROM op_exam_attendees;      -- id=11 exam=11 student=5 marks=20
SELECT * FROM op_marksheet_line;      -- id=7  marksheet_reg_id=NULL student=5 total_marks=92
SELECT * FROM op_result_line;         -- id=11 marksheet_line_id=7 exam=11 student=5 marks=92
SELECT exam_id, count(*) FROM edu_grade_history GROUP BY 1;   -- exam=11, n=186
SELECT count(*) FROM op_result_template;      -- 0
SELECT count(*) FROM op_marksheet_register;   -- 0
SQL
```

> ⚠ **读共享开发库必须自带时刻**：本库同时有代理在改 `edu_portal` 的请假功能与 `edu_brand`，读数随时在变。**§3.3 的 186 条读数只在 "2026-09-24 09:53:57 UTC" 这一刻成立**，复现时数字可能不同 —— 但 "attendee 与 result_line 数值不一致" 这个**结构性事实**不随时间改变。

### 14.5 试过并排除的路径（**给下一个人省时间**）

| # | 试过的做法 | 结果 | 结论 |
|---|---|---|---|
| E1 | 在 `custom_addons/` 里找 `generate_result` 的调用者 | 0 命中（只有 `seed_batch2.py` 的**手写替代**） | **没有自动桥**。别再去 `edu_portal`/`edu_assess` 里找 |
| E2 | 找 cron / automation rule 自动生成 marksheet | 全仓 `data/*.xml` 无相关 cron | **没有定时任务** |
| E3 | 找 `op.result.line` 的 `create`/`write` override 做同步 | `result_line.py` 全文 83 行，只有 `unlink` 一个 no-op override | **没有** |
| E4 | 假设"学生页走自己的 ACL，所以教务缺 ACL" | 实测 `op.marksheet.line` / `op.result.line` 的 ACL **只给 `group_op_exam_user`/`group_op_exam_admin`**，而教务**通过 `group_tuning.xml:24-25` 已隐含拿到这两个组** ⇒ **教务不缺 ACL** | **权限不是断点，数据链才是**。这个假设会把人带偏 |
| E5 | 假设 `/grade-book` 有 `?student_id=` 参数可以代看 | 读 `batch2.py:1034` 签名 —— **只有 `**kw`，函数体完全不读参数** | 参数**不存在**，不是"没传" |
| E6 | 用 `psql -c "多行 SQL"` 走 ssh | shell 吃引号，报假的 GROUP BY 错误 | 必须 heredoc（§14.2） |
| E7 | 期待"本地演示环境因为数据齐，能看出全链路正常" | 本地库里 `op_result_template`/`op_marksheet_register` **都是 0**，成绩是手写的 | **本地演示的"正常"是假的**，不能作为验收基线 |
| E8 | 在 code-map 里找 `edu_assess` | `code-map.md:38` 说"9 个 edu_*"，实际 **13 个** | **code-map 该处过时**（本文登记；属文档同步问题，本次不改文件） |

### 14.6 参考的仓内文档（本文与它们的关系）

| 文档 | 关系 |
|---|---|
| `docs/plans/evaluation-rebuild-design.md` | §2.3 明确把"成绩册"排除在评估域之外（`:104`）、T3 收口条件（`:183`）⇒ **本文是该文档划出的那块空白的第一份调研**。§4.2（名单快照为什么必要）、§4.3（矩阵三面）、§4.4（"列 = 数据不是字段"）被本文直接引用为形态依据 |
| `docs/research/evaluation-rebuild.md` | §2.2/§2.3（`spreadsheet` 社区版只读、`web_grid` 企业版）、§4（Moodle/Canvas）、§5（国内同类）、§7.1（Properties 被设计推翻）⇒ 本文 §5、§8.4 引用其结论，**不重复调研** |
| `docs/plans/study-hub-v3-design.md` §3 | 成绩三层的数据流原文（`:151`）⇒ 本文 §9.2 的改造对象 |
| `docs/ops/jiaowu-manual.md` | §8.1（`:152` 教务的后台成绩入口）、§8.2（`:173` "设计上就是跳回首页"）⇒ 本文 §2.2/§4.3 的一手依据 |
| `docs/plans/ux-v3-delivery.md` | `:575` 记录生产无教师账号、`op_faculty` 仅 1 条「待定」且未绑定账号 ⇒ 本文 §4.1 的旁证 |
| `tests/smoke/class_change_request.py` | `:189-203` V16（成绩存放处）、`:563-569` / `:773-781` **校长拍板 P5**（换班后旧班成绩仍可见）⇒ 本文 §6.3/§7.3 的硬约束来源 |
| `docs/audit/deprecated-inventory.md` | `:289` 记录 `UNIQUE(...)` 对 NULL 行失效的实证、`:291` 记录 `edu.course.subject` 关系表落地 ⇒ 本文 §7.1-B 的被评者键设计依据 |

---

### 14.7 对外调研的死路记录（**下一个人不要重走**）

本次**没有可用的通用搜索引擎**。逐条记录（**检索工具 + 失败现象**）：

| 工具 | 状态 | 失败现象 |
|---|---|---|
| **DSH 内置 `web_search`** | ❌ **全程不可用** | 每次返回 `Command Code web search returned an unparseable response body`（**试 6 次全失败**，单条 / 多条 query 均如此）。本文作者独立复现 1 次，同样失败 |
| Bing（cn.bing.com） | ❌ 中文多词不可用 | 「北京大学 招生」只返回北京旅游结果；「智学网 成绩查询」返回「智」字词典页；`site:feishu.cn 成绩` 的 `site:` 被完全忽略并返回 chsi.com.cn。只有单个短品牌词（钉钉、智学网）能出正确结果 |
| Baidu（带 BAIDUID cookie） | ❌ | 返回 1,438 字节反爬页，result 块数 = 0 |
| DuckDuckGo（html / lite） | ❌ | `urlopen error timed out` |
| Mojeek | ❌ | HTTP Error 403 Forbidden |
| SearxNG（searx.be） | ❌ | Connection refused |
| Ecosia / Startpage / Brave / Yandex / Google | ❌ | 无关键词命中 / 超时 / Connection reset by peer |
| Exa（`agent-reach` 建议路径） | ❌ | `Unknown MCP server 'exa'`（**未配置**） |
| **直连官方站 + 站点 llms.txt + 破解站内搜索 API** | ✅ **唯一有效** | 本轮**全部**一手证据由此路径取得（方法见 §5.4.7） |

**另两条"抓取到但不可用"的记录**（本次作者亲测）：

| 尝试 | 结果 |
|---|---|
| `raw.githubusercontent.com/moodle/moodle/{main,master}/lib/db/install.xml` 与 `/grade/lib.php` | **404** —— Moodle 仓库的默认分支名与本机猜测不符；**未进一步枚举分支**，故 Moodle 表结构的源码级复核**未完成**（U10） |
| `raw.githubusercontent.com/instructure/canvas-lms/stable/{app/models/submission_version.rb, app/controllers/gradebook_history_api_controller.rb}` | **404**；另一次请求 **tool call timed out after 30000ms** |

⇒ **结论**：**通用搜索引擎在本环境不可用**。下一个人应直接走「官方站 + llms.txt + 站内搜索 API」（§5.4.7），并把这条写进 `docs/research/README.md` 作为**可复用解法**。

---

---

## 附录 A｜「成绩簿页给教务可编辑形态」的同类先例与查重（2026-10-03，task-18 增补）

> 背景：用户原话「我希望教务人员的这个成绩薄页面，可以改成给学生录入成绩。」
> 本轮**没有新造录入引擎**，只做入口分流（`custom_addons/edu_portal/controllers/grading.py`），
> 因此本附录只补两件事：**其一，这件事在同类系统里怎么做；其二，本仓有没有第二套现成实现（查重）**。

### A.1 同类系统：可编辑的「成绩簿」= 落在**评分管理权限**之下

本文 §5.1.6 与 §5.2 的源码级取证已经给出答案（Moodle commit `89ae02d0007418c50f0911148137f4cb3bd67f4a`；Canvas `app/controllers/gradebooks_controller.rb`）：

| 系统 | 事实 | 出处 |
|---|---|---|
| Moodle | 「教师网格 grader」（`/grade/report/grader/index.php?id=<courseid>`）本身就是**可编辑的成绩簿**：`grade_report_grader::process_data` → `update_final_grade(..., 'gradebook', ...)`；学生看自己的分数走**另一个报表**（`/grade/report/user/index.php`） | 本文 §5.1.6 |
| Canvas | Gradebook 页的授权 = `authorized_action(@context, @current_user, [:manage_grades, :view_all_grades])`（`GradebooksController#show`）⇒ **进得了成绩簿页 = 有评分管理权限**；学生的成绩是另一个入口 | 本文 §5.2 |

两条合起来支持同一个结论：**「成绩簿」这个入口在成熟系统里本来就是「谁能管分谁就能在这里录/改」，不是学生专属报表。** 本仓原先把它写死成学生专属（非学生一律拒止），与该惯例不一致。

差异如实记：Moodle 与 Canvas 都把「可编辑网格」放在**独立路由**上（grader / gradebook），本仓本轮选择**同一 URL 两态**。依据是本仓自己的既有做法 —— `/downloads` 的「普通态 / 教务处管理模式」就是同页两态，且旧 `/downloads/manage|upload` 已被降级成 302 兼容跳转（code-map §4），方向一致。

### A.2 查重（第 0 步）：本仓已有一套「教务录分」，本轮不新建第二套

- 既有实现：`custom_addons/edu_portal/controllers/grade_entry.py` 的 `/grade-entry` 与 `/grade-entry/save`（2026-09-29 交付；端到端探针 `tests/smoke/grade_entry_probe.py` 44 条断言；交付报告 `tests/smoke/GRADE_ENTRY.md`）。它已支持教务（`privileged_staff()` → 全校）与任课教师（按 `op.session` 的 `(faculty_id, batch_id, subject_id)` 收敛）；写侧 `op.exam.attendees` 与读侧 `op.result.line` 双写，留痕走 `edu.grade.history`。
- 结论：**本轮不新建模型、不新建录入路由**，只把 `/grade-book` 在教务 / 超管身份下的形态接到那套引擎上（直接复用其控制器方法），避免「同一功能两个录入口径」。

### A.3 本轮取证的边界（**未验证项**，不得当结论用）

- `web_search` 在本环境**仍不可用**：本次返回 `HTTP 400 insufficient credits`（试 2 次）。与本文 §14.7 记录的「unparseable response body」是同一类故障的不同形态。
- `web_fetch` 对 `raw.githubusercontent.com` **时通时断**：Canvas `gradebooks_controller.rb`（master）**成功取回一次**（93,107 字节，首行 `# frozen_string_literal: true`，类名 `GradebooksController`），随后重试同一 URL 变为 `TypeError: fetch failed`；Moodle 的 `grade/report/grader/db/access.php` **两次均失败**，`github.com/moodle/moodle/raw/main/...` 返回 **404**。本机 `curl` 直连亦为 `Connection reset by peer`。
- 因此本附录的 Moodle / Canvas 结论**沿引本文 §5.1.6 与 §5.2 已入库的源码级取证**（带 commit 与文件符号），**不是本轮重新取回的**；本轮只独立确认了「Canvas 该文件存在、类名与授权语句如本文所述」这半点（未能逐行复核）。
- 未验证：同类系统里是否存在「教务只能录、不能改」的独立开关（Moodle 的 grader 是同一套写入口，本轮未发现这样的开关；**不等于不存在**）。

*本文档为调研交付物，不含任何代码改动。所有生产库访问均为只读 `SELECT`。*



