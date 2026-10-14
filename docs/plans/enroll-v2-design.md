# 学生自主报课 + 教务审批（enroll-v2）设计文档
> **状态**：`已上线` ｜ **主题**：`学生自主报课` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 状态：设计定稿（第 2 期）｜关联实现：custom_addons/edu_portal 内新增（模型 + 控制器 + 视图）
> 基线：edu_portal 19.0.1.10.0（2026-08 第 5 批后）
> 角色：architect（需求/设计员）→ engineer 实现 → reviewer 验证 → deployer 部署
> 目标读者：实现工程师、审查员、部署员。所有待决项已给默认裁决，工程可直接开工。

---

## 0. 背景与目标（一句话）

学生（如王佐）在门户从 **课程 / 班级 / 科目目录** 自主勾选课程与科目，提交「选课注册单」
（复用基座 `op.subject.registration`，state=submitted）；教务处/管理员在门户「教务审批」
聚合页一键 **通过 / 驳回**——通过时自动把该学生的在读档案 `op.student.course`（state=running）
与其 `subject_ids` 建立/更新（含科目挂靠），驳回时经站内通知引擎告知学生；学生端「我的申请」
看进度、「我的课程」/LMS 学习/课表随之联动。全程审计入库，不动基座源码，只 `_inherit` 扩展。

---

## 1. 名词与现状梳理（勘察结论，已核实代码与本地库）

### 1.1 数据模型（基座 openeducat_core，不改）
| 模型 | 关键字段 | 说明 |
|---|---|---|
| `op.course` | code/name/subject_ids(m2m `op.subject`)/program_id | 课程（如 CRS-BED 教育学士） |
| `op.batch` | code/name/**course_id**/start_date/end_date | 班级，挂在课程下 |
| `op.subject` | code/name/**subject_type**(compulsory/elective)/active | 科目 |
| `op.student.course` | student_id/course_id/batch_id/**subject_ids(m2m)**/roll_number/academic_years_id/academic_term_id/state(running/finished) | **学生×在读档案**；唯一约束 (student_id,course_id,batch_id) |
| `op.student` | user_id / course_detail_ids(o2m) / partner_id | 学生 |
| `op.subject.registration` | student_id/course_id/batch_id/compulsory_subject_ids(m2m)/elective_subject_ids(m2m)/state(draft/submitted/approved/rejected)/max_unit_load/min_unit_load | 选课注册单（社区版已有） |

- `op.subject.registration` **已有状态机**：`draft → submitted → approved/rejected`；
  方法 `action_submitted / action_approve / action_reject / get_subjects / action_reset_draft`
  （`openeducat_core/models/subject_registration.py`）。
- 基座表单按钮：Submit 仅 backoffice/faculty；Approve/Reject 仅 faculty（`subject_registration_view.xml`）。
- 基座 `get_subjects()` 只把 `course_id.subject_ids` 中 compulsory 科目灌进
  `compulsory_subject_ids`；**并不会生成选课页目录**。

### 1.2 基座 action_approve 的缺陷（本设计必须规避）
基座 `action_approve()`（subject_registration.py:64）：
1. 拼 `compulsory + elective` 科目 id；
2. search `op.student.course`（student_id, course_id）——**找不到就抛
   `ValidationError("Course not found on student's admission!")`**；
3. 找到则只 `write({'subject_ids': …})` + `state='approved'`；
4. 不建档案、不写 roll_number/academic_years/term、不处理 batch、不通知、不审计。

**用户场景（王佐）已存在 op.student.course 13**，走基座 approve 不会报错，但它：
- 不会更新 batch / academic_term / 学期；
- 不通知、不审计；
- 若该学生没有档案（家长代为录入或漏建档），直接抛错中断审批。

> 结论：**门户侧不调用基座 `action_approve`**，用自研 `_inherit` 方法 `action_enroll_approve()`
> 完整处理（见 §3.4）；保留基座方法不动（后台旧按钮仍可用，且行为不回归）。

### 1.3 现有学生端 4 个入口（勘察结论 + 去留建议）
| 入口 | 现状 | 路由位置 | 建议 |
|---|---|---|---|
| ① `/my-courses`（课程） | **公开模块 edu_public 的“我的课程”**：只列 `op.student.course` 对应 course 卡片，点卡片无详情，`t-call="website.layout"` 非门户壳 | edu_public/controllers/main.py:252 + edu_public/views | **改造为**学生「我的课程」学习中枢（读课程目录 → 点进 LMS 科目学习 `/my/courses`），见 §4.5 |
| ② `/my/courses`（LMS 课程/科目） | 学生视图 `_subjects_for` = `scs.mapped('course_id').mapped('subject_ids')`，**等于在读档案 course.subject_ids** | edu_portal lms.py + views/lms.xml | 保留，**改为读档案 `subject_ids`** 联动（改一处 `_subjects_for`） |
| ③ `/subject/registration`（科目注册列表） | 只读学生列表 + 无「新建注册」、无教务审批 | edu_portal batch3.py:350 | 保留路由，改造为「我的申请」列表 + **新建注册入口**（新增 `enroll` 路由群） |
| ④ `/student/timetable`（周课表） | 按在读 batch 显示（`student_course()` 取第一条 running） | edu_portal scheduling.py | 保留；报课后若 batch 变化，课表自动跟随，无需改代码 |

> 新增一组路由（全部新路径，无冲突）：
> - `GET /subject/enroll`：报课目录页（课程/班级/科目选择）
> - `POST /subject/enroll/save`：提交注册单（state=submitted）
> - `GET /registrar/subject/approvals[/<rid>]`：教务审批聚合列表 + 详情
> - `POST /registrar/subject/approvals/<rid>/set_state`：通过/驳回（带驳回原因）
> - `GET /student/subjects`：学生「我的已选科目」（我的申请页顶部横向卡）
> - 可选 GET：`/subject/enroll/terms`（按班级/学期排课冲突预检，P2）

### 1.4 角色与现有权限（不开新组）
- `openeducat_core.group_op_back_office_admin` = 教务处/Registrar/Manager（implied group_system + faculty + partner_manager）
- `openeducat_core.group_op_faculty` = 教师
- `base.group_portal` = 学生门户；`base.group_user` = 内部
- 铁律：**不建自定义组**，复用上面；**学生数据隔离**由 `student_login_rule`（ir.rule）控制；
  门户读多用 `sudo()`（既有惯例），门户写用控制器判角色。

### 1.5 门户技术栈（已核实，写代码遵循）
- 页面模板统一 `t-call="edu_portal.edu_page"`；角色判断变量在壳内：
  `b11_stu`（学生）、`b11_fac`（教师）、`b11_par`（家长）、`b11_sys`（system）——
  其中 `b11_stu = not b11_par and 有 op.student`；**学生身份不另判断家长**。
- 写操作 = POST 兄弟路由 + csrf_token；中文文案；时间/百分比在控制器预格式化，
  **QWeb 模板内不出现 % 格式化**。
- 审计 = `edu.audit.log._log(action, model, res_id, res_name, detail)`（失败不阻断）。
- 通知 = `edu.message._notify_event(event_key, recipient_user, body, sender_uid)`，
  事件 key 登记在 `models/notify_pref.py NOTIFY_EVENTS`（新 key 在此追加，学生可在
  `/my/notify` 静音）。
- 审批聚合先例：`roles.py /leave/approvals[/<id>] + /leave/set_state`（列表 chips、详情页、
  `_notify_applicant`、`reject_reason` 必填、审计）与 `_approval_alerts()`（教师/教务首页待办聚合）。
- 后台菜单先例：`views/approval_backend.xml`「教务审批」根菜单（groups="base.group_user"）。

---

## 2. 业务流（端到端）

### 2.1 学生报课流（王佐场景）
```
王佐登录 /my/home →（入口）学业组卡片「报课选科 / 课程注册」→ /subject/enroll
  ① 页首展示在读档案摘要：课程 CRS-BED / 班级 B1 人文一年级 / 学期 term1 / 状态 running
     （student_course() 取 running 档案）
  ② 默认定位当前在读 course_id 与 batch_id（下拉/目录按该课程列出）
  ③ 课程目录区：课程卡片（只读，来自可报课程范围；默认含在读课程 + 同 program 兄弟课程）
  ④ 选择课程后联动显示其班级（op.batch where course_id=…，未结束 end_date >= today）
  ⑤ 选择班级后列出科目池：
       - compulsory 科目：来自 course_id.subject_ids（subject_type=compulsory）——**自动勾选、锁定不可取消**
       - elective 科目：同 source subject_ids 中 subject_type=elective，可多选
       （当前数据：compulsory 31 / elective 2——大多数学位课程无 elective；页面须优雅处理“无选修”）
  ⑥ 「提交选课注册单」→ POST /subject/enroll/save
     服务端校验：学生必填；course/batch 必填；batch.course_id == course_id；
     compulsory 科目必须全量在注册单 compulsory_subject_ids 中（防绕过）；
     elective 只能来自课程科目池；科目数与 unit_load（若配置）校验——
     通过 → 创建 op.subject.registration：
       {student_id, course_id, batch_id,
        compulsory_subject_ids: 课程必修科目,
        elective_subject_ids: 学生勾选选修,
        state: 'submitted'}   ← 直接提交，不做草稿
     重复提交防护：同一学生同一 (course,batch) 存在 submitted/approved 的注册单时，
       仍允许再提交新单（档案可能因驳回后重提）；**但 approved 后禁止再为同档案重复报**
       （页面把该 (course,batch) 置灰并提示“已通过，无需重复申请”）；
       同一学生存在 submitted 且同 (course,batch) 时给出提示但允许继续（教务会取最新）。
     审计：'报课提交' edu.subject.registration <rid> '<课程> <班级> 必修N 选修M'
  ⑦ 回跳 /subject/registration?box=submitted（列表 + 成功横幅）
  ⑧ 若目标班级 != 在读档案班级（如转班/合班重选），教务通过时会更新档案 batch（见 §3.4）。
```

### 2.2 教务审批流
```
教务/管理员登录 →（入口）教师/教务工作台「待办提醒」新增「待批选课」卡 →
  /registrar/subject/approvals?filterby=pending
  列表 chips：待审批 / 已通过 / 已驳回 / 全部；搜索：单号/学生/课程；分页 20
  行：单号(链详情) / 学生 / 课程 / 班级 / 申请时间 / 科目数 / 状态 / 操作(通过|驳回)
  详情 /registrar/subject/approvals/<rid>：
    学生、课程、班级、学期(若有)、状态步骤条（已提交→审批中→已通过/已驳回）、
    必修科目 chips + 选修科目 chips、当前在读档案摘要（course/batch/subjects/state）、
    **差异提示**（若该学生同 course 已有档案且科目不同 → 醒目黄条“本次将覆盖其 N 门科目”）
  操作：
    POST …/set_state  state=approved + （可选）remark：
       自研 action_enroll_approve（§3.4）：
         - 校验；建/更新 op.student.course（详见 §3.4）；
         - 注册单 state=approved；写 approved_at/approved_by；
         - 审计 '选课审批' … '通过'；经 _notify_event('subject_reg_result') 通知学生
         - 打开下一页（next 回跳列表/详情，仅接受 /registrar/ 前缀）
    POST …/set_state  state=rejected + reject_reason **必填**：
        注册单 state=rejected + reject_reason；审计；通知学生（含驳回原因）
  删除/撤回：不提供（教务侧仅通过/驳回；学生侧对 submitted 可提供“撤回”可选 P1）。
```

### 2.3 学生「我的申请 / 我的课程」联动
- `/subject/registration`（改造）：顶部“新申报课”按钮 + “我的已选科目”横卡（approved 的
  course→subject 集）+ 注册单列表（状态徽章、详情链接同现有，新增科目 chips/取消理由展示）。
- `/my/courses` LMS 学生视图 = **在读档案 `subject_ids`**（§4.5）。报课通过后，
  学生 /my/courses 立即可学新科目；若仅加科目而课程不变，学程自动多卡。
- `/student/timetable`：按在读档案 batch 排课，通过后若改班级，周课表自动换班——无需改代码。

### 2.4 状态机总览（谁驱动什么）
```
                [学生]              [教务/管理员]            [系统]
draft(不从前端建)                   后台老按钮可 draft
submitted ◄──── POST enroll/save（直接建 submitted）
submitted ──────► approved   action_enroll_approve：建/更新档案+科目、通知、审计
submitted ──────► rejected   action_enroll_reject：写 reject_reason、通知、审计
rejected ─(可选 reset_draft，仅后台)─► draft
approved 终态（不允许再批改；要改走新的注册单或后台手改档案）
```
> 前端不出现 draft（学生直接提交）。保留基座动作方法名兼容后台（不删不改基座）。

---

## 3. 设计落点（工程可直接照做）

### 3.1 新增模型扩展（edu_portal/models/registration.py，`_inherit`，不新建表）
```python
class OpSubjectRegistration(models.Model):
    _inherit = 'op.subject.registration'

    # 用于「同一 (course,batch) 是否已批过」判断与页面置灰提示
    applicant_note = fields.Char('申请备注', help='学生填写的选课说明/备注')
    approved_at = fields.Datetime('审批时间')
    approved_by = fields.Many2one('res.users', '审批人')
    reject_reason = fields.Char('驳回原因')          # 基座没有；补上（对齐 leave 惯例）
    submitted_at = fields.Datetime('提交时间')         # create 时自动写

    def action_enroll_approve(self): ...   # 见 §3.4（门户/后台两用，门禁在控制器）
    def action_enroll_reject(self): ...    # 通知 + 审计 + state
    def _notify_student(self, result): ... # 复用 edu.message._notify_event
    def _subject_payload(self): ...        # compulsory ∪ elective ids（去重有序）
```
> `compulsory_subject_ids / elective_subject_ids` 沿用基座字段，不另加 m2m 表；
> `op.student.course.subject_ids` 仍为事实源（LMS/课表读取它），注册单仅作“申请单据”。

### 3.2 控制器新增（edu_portal/controllers/enroll.py，自包含，不碰现有路由方法）
```python
class EduEnrollPortal(http.Controller):
    # ---- 学生端 ----
    @http.route('/subject/enroll', type='http', auth='user', website=True)
    def enroll_catalog(self, **kw): ...
        # 数据：student_course() 摘要 + 可报课程 + 已选 batch 的科目池（compulsory/elective 分组）
        # 预选：同 (course,batch) 已 approved 则仅展示摘要与“已通过”黄条，禁重复提交
        # 模板：edu_enroll_catalog（edu_page 外壳；纯 GET 渲染 + JS 联动选课程→班级→科目）
    @http.route('/subject/enroll/save', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def enroll_save(self, **kw): ...
    @http.route('/student/subjects', type='http', auth='user', website=True)
    def my_subjects(self, **kw): ...        # 我的已选科目（approved 聚合，返回给 /subject/registration 嵌段）

    # ---- 教务侧 ----
    @http.route('/registrar/subject/approvals', type='http', auth='user', website=True)
    def approvals(self, **kw): ...          # 门禁 current_faculty() or privileged_staff()，仿 leave_approvals
    @http.route('/registrar/subject/approvals/<int:rid>', type='http', auth='user', website=True)
    def approval_detail(self, rid, **kw): ...   # 详情 + 差异提示 + 主行动表单
    @http.route('/registrar/subject/approvals/<int:rid>/set_state', type='http',
                auth='user', website=True, methods=['POST'], csrf=True)
    def set_state(self, rid, **kw): ...      # approved→action_enroll_approve; rejected→reject_reason 必填
```
路由前缀 `/registrar/…` 与 `/subject/enroll` 均无冲突（已 grep 全仓）。

### 3.3 视图/导航新增
1. `views/enroll.xml`：`edu_enroll_catalog`、`edu_enroll_success`(可并入 catalog box)、
   `edu_registrar_subject_approvals`、`edu_registrar_subject_approval_detail`、
   `edu_student_subjects`（嵌段或独立页）。
2. **学生首页学业组**（batch2.py `acad_hrefs`，不删旧入口）：
   - 保留 `my-courses`（现“课程”卡，/my-courses 改造后读档案科目 → 学习中枢）；
   - 保留 `subject/registration` 卡（改名“报课选科”描述“课程/班级/科目注册与我的申请”）；
   - 保留 `course/change/request`、`student/timetable`（转班/课表仍独立存在）。
3. **教师/教务工作台**：`_approval_alerts()` 增加
   `{'key':'subject_reg', 'title':'待批选课', 'count': submitted 数, 'href':'/registrar/subject/approvals', ...}`
   （教务处与有 op.faculty 的教师均走门户聚合页；privileged_staff 无档案者仍门户页）。
4. **后台“教务审批”根菜单**（approval_backend.xml）追加 menuitem 子项
   `menu_edu_subject_registration_approval → 选课审批`（act_window 直连
   op.subject.registration list+form，domain state=submitted，groups 沿用既有）——
   供习惯后台的教务一键处理；**后端表单按钮仍调自研 action_enroll_approve/reject**
   （通过 xpath 替换基座表单按钮 name，基座方法仍保留）。
5. **门户左侧角色导航**（edu_portal_templates.xml，`<t t-if="b11_stu">` 学习组内）：
   在“课程(/my-courses)”旁新增一行“报课选科 → /subject/enroll”，学籍信息不变；
   教师侧“教学安排”组下方若 fac 则加“选课审批 → /registrar/subject/approvals”。
6. `scripts/gen_icons.py` SPEC 追加瓦片：`subject/enroll`（报课）、`registrar/subject/approvals`
   （教务审批）——遵循图标铁律。
   > 实现裁决（repair round-2 确认）：两入口已采用首页卡片引擎 FA 彩色兜底
   > （batch2.py FA_HOME_ICONS / `_YONGYUE_CARDS` 的 `fa-pencil-square-o`），
   > **gen_icons.py 瓦片列为可选后续**；若后续补瓦片需同步移除 FA 兜底，避免双源。

### 3.4 核心动作：action_enroll_approve（规避基座缺陷，伪码）
```python
def action_enroll_approve(self):
    """门户与后台共用：通过注册单 = 建/更新 op.student.course + 科目 + 通知 + 审计。"""
    Registration = self.env['op.subject.registration']
    for rec in self:
        if rec.state != 'submitted':
            continue  # 幂等/终态保护（approved/rejected 不再流转）
        student = rec.student_id
        course = rec.course_id
        batch  = rec.batch_id
        if not (student and course and batch and batch.course_id.id == course.id):
            raise ValidationError('注册单缺少学生/课程/班级，或班级不属于该课程。')
        # —— 找“同学生同课程”的当前在读档案（可含 batch 差异），没有则 None ——
        sc = self.env['op.student.course'].sudo().search([
            ('student_id', '=', student.id),
            ('course_id', '=', course.id)], order='id', limit=1)
        subject_ids = sorted(set(rec.compulsory_subject_ids.ids + rec.elective_subject_ids.ids))
        if not sc:
            # 学期取同课程档案的 term；否则取日期覆盖今天的进行中 term（无则留空）
            term = (rec.academic_term_id or self._running_term())
            sc = self.env['op.student.course'].sudo().create({
                'student_id': student.id,
                'course_id': course.id,
                'batch_id': batch.id,
                'academic_years_id': term.academic_year_id.id if term else False,
                'academic_term_id': term.id if term else False,
                'state': 'running',
                'subject_ids': [(6, 0, subject_ids)],
            })
        else:
            # 更新档案到本次班级（转班/合班），并整体覆盖科目集（注册单=最新意愿）
            vals = {'subject_ids': [(6, 0, subject_ids)], 'state': 'running'}
            if batch.id != sc.batch_id.id and (not sc.batch_id or batch 属于同一课程):
                vals['batch_id'] = batch.id
            sc.write(vals)
        rec.write({
            'state': 'approved',
            'approved_at': fields.Datetime.now(),
            'approved_by': self.env.uid,
        })
        rec._notify_student('approved')          # → edu.message._notify_event('subject_reg_result', …)
        self.env['edu.audit.log'].sudo()._log(
            '选课审批', 'op.subject.registration', rec.id, rec.name or '',
            '通过：档案 %s 科目 %d 门' % (sc.name or sc.id, len(subject_ids)))
```
要点：
- **“找不到档案”不再抛错**，而是自动建档（建即 running、回填学期）——覆盖家长录入等场景；
- **王佐场景（档案 13 已存在）**：走 else 分支更新 batch（若一致则不动）并覆盖 subject_ids，
  LMS/课表即时联动；
- 通过后同一 (student,course,batch) 的重复 submitted 单，教务仍可批（后者覆盖）——
  页面用“同课程已通过”黄条提示，不硬禁；
- batch.course_id 校验 + 科目必须来自 course.subject_ids（在 enroll_save 与 approve 双端校验）。

### 3.5 通知
- 新事件 key：`('subject_reg_result', '选课审批结果')` 加入
  `edu_portal/models/notify_pref.py NOTIFY_EVENTS`（页面 /my/notify 自动出现开关）。
- `_notify_student`：
  - approved：`【选课通知】您的选课申请 <name>（<课程> · <班级>）已通过，共 N 门科目已生效。`
  - rejected：`【选课通知】您的选课申请 <name> 已被驳回。<驳回原因>`（reject_reason 必填）
  - 收件人 student.user_id；无账号/就是审批人则跳过；失败只告警（对齐 leave.py）。

### 3.6 审计埋点（edu.audit.log，控制器或模型动作内统一）
| action | model | detail |
|---|---|---|
| 报课提交 | op.subject.registration | 学生/课程/班级/必修N选修M |
| 选课审批（通过） | op.subject.registration | 通过：档案<id>科目N门（建/更新） |
| 选课审批（驳回） | op.subject.registration | 驳回：原因<…> |
| （可选）撤回 | op.subject.registration | 学生撤回 |

---

## 4. 入口/导航整合（含 4 入口去留——已确认默认）

### 4.1 决策汇总
| 入口 | 决策 | 理由 |
|---|---|---|
| /my-courses（edu_public） | **改造升级**为学生“我的课程”中枢；若改动大则保留页面仅把 course 卡链接指向 /subject/enroll | 原页面仅 course 卡无科目学习，信息量低；现 LMS 才是学习页 |
| /my/courses（LMS） | 保留；`_subjects_for` 学生分支 **student_course 档案 subject_ids** 联动 | 第②勘察指出当前=course.subject_ids，与个人报课脱节 |
| /subject/registration | 保留路由并改造：+ 新建入口 + 我的已选科目 + 状态/原因展示 | 学生“我的申请”落点 |
| /student/timetable | 保留（不动） | 已自动随档案 batch 联动 |
| 新增 /subject/enroll | 新报课目录页 | 主体新功能 |
| 新增 /registrar/subject/approvals[/rid] | 教务门户审批聚合 | 主体新功能 |
| 后台“教务审批→选课审批” | 新增菜单项 + 基座表单按钮换绑自研 approve/reject | 后台也可办，防基座缺陷 |

### 4.2 首页卡片/导航细节（工程师注意）
- **不改** batch2 `acad_hrefs` 既有顺序与隐藏集，避免回归隐藏开关 `_DEFAULT_HIDDEN_CARDS`
  白名单机制（只加新 href 不进 hidden）。
- `subject/registration` 卡描述文案从“选修课程与科目的流程”改为
  “课程/班级/科目选报与申请进度”（保持中文）。
- 新增“报课选科”高曝光入口：学生卡片区（_YONGYUE 或学业组首位可选）；
  折中默认：学业组内排在 `my-courses` 之后（desc 指向报课），`subject/registration` 卡改为
  其列表页别名入口。
- 教师/教务首页 `_approval_alerts` 追加待批选课（上文 3.3-3）。

### 4.3 各角色可见矩阵（默认）
| 动作 | 学生 | 教师 | 教务(Registrar/Admin) | 家长 | 内部普通用户 |
|---|---|---|---|---|---|
| 浏览课程/班级/科目目录 | ✅ 仅“可报范围”(默认=在读课程+同 program 课程+全 active 课程，见待决D2) | ✅ 全校目录（如需） | ✅ | ❌（孩子读卡保留） | ✅ 只读（同教师口径保守） |
| 提交报课单 | ✅（本人） | ❌ | ❌（可代录：表单隐藏学生字段=本人） | ❌ | ❌ |
| 看自己的申请 | ✅（本人） | ❌ | ✅全部 | ❌ | ❌ |
| 审批（通过/驳回） | ❌ | ✅（门户聚合，仅 submitted） | ✅ | ❌ | ❌ |
| 建/更新档案 | 间接（通过审批触发） | ❌（后台 faculty 有 op.student.course 读写=基座现状，不扩权） | ✅ | ❌ | ❌ |
| 接收通知 | ✅ | — | — | ❌（P2 再议家长） | — |
| 审计查询 | ❌ | ❌ | ✅ | ❌ | ❌ |

### 4.4 异常/防误（服务端强制，非仅前端）
1. 非学生（无 op.student）访问 /subject/enroll → redirect /my/home（控制器判空，铁律）。
2. 课程/班级非法：batch.course_id != course_id → 拒绝。
3. 选修科目不属于该课程 subject_ids → 拒绝。
4. 必修科目缺失（绕过前端）→ 服务端补齐或拒绝（选择“补齐”默认，见 D1）。
5. approved 终态不重复流转（方法内 state 守卫）。
6. 已通过的同 (course,batch) 新单仍可批但页面黄条警示；不硬禁（教务有改主意场景）。
7. csrf 全程；next 回跳仅限 /registrar/ 前缀（防开放跳转，对齐 leave_set_state）。
8. 驳回原因必填；不填返回错误横幅。

---

## 5. 待决项与默认裁决（默认已可用，用户可改）

| # | 待决 | 默认裁决（工程照做） | 影响 |
|---|---|---|---|
| D1 | 必修科目：注册单 compulsory 自动带全，还是允许缺省提交 | **自动带全 + 服务端补齐**（compulsory 不可取消） | 简单、语义对（必修=本课程既定） |
| D2 | 学生可报课程范围 | **在读课程 + 同 program 课程 + 全部 active 课程**（目录只读、不锁定）；如需“仅限在读”改一处 domain | 王佐可看全部 7 门课目录，报课仅影响自己档案 |
| D3 | 是否支持“申请撤回”（学生反悔） | P1 可选，本期**不做**（rejected 可重提新单；submitted 请私信教务） | 减小范围 |
| D4 | 家长是否代孩子报课 | **不做**（家长端只读孩子档案；P2 可加） | 权限面收窄更稳 |
| D5 | 审批人范围 | 有 op.faculty 的教师 + privileged_staff（教务处/管理员）；**不需要教师档案** | 复用 /leave/approvals 门禁 |
| D6 | 学期/学年从哪来 | 注册单无学期字段 → **approve 时取学生同 course 档案的 academic_term_id；否则取日期覆盖今天的进行中 term（`term_start_date<=today<=term_end_date`），无则留空**（op.academic.term 无 is_current，用日期判定） | 建档/更新不丢学期 |
| D7 | 选课是否校验排课冲突（216 节 op.session 按 batch） | **P2**（本期不做自动冲突检测；目录页展示“该班级已有 N 节排课”只读信息即可） | 控制本期范围 |
| D8 | 科目 unit load 上限 | 若 course.max_unit_load>0 且所选科目有 weightage 之和超标 → **校验并提示**；否则不校验 | 数据缺失时零门槛 |
| D9 | 我的申请默认排序 | **id desc（最新在前）**，状态筛选 chips 同上期 | 一致性 |

> 待用户拍板项：D2 可报范围、D7 是否做冲突提示、D4 家长代报。若用户未回复，工程按默认实现。

---

## 6. 王佐走通路径（验收剧本）
```
前提：王佐=op.student 11；op.student.course 13（CRS-BED / B1 人文一年级 / term1 / running）
1. 王佐登录 → /subject/enroll
   断言：页首在读摘要=CRS-BED·B1；目录出现课程列表（含 CRS-BED）；科目池=CRS-BED subject_ids
        （本地为 0 门时显示空态“该课程暂未配置科目目录”，不报错）
2. 选 CRS-BED + B1 → 勾选（若数据存在）若干科目 → 提交
   断言：创建 op.subject.registration state=submitted，name 走 SR 序列；审计 1 条；横幅成功
3. /subject/registration 列表出现该单（状态=已提交），顶部“我的已选科目”为空/旧
4. 教务登录 → /registrar/subject/approvals（默认 pending）看到该单 → 详情 →
   若档案 13 与单课程相同则显示差异提示（科目将被覆盖为 N 门）→ 通过
   断言：op.subject.registration.state=approved + approved_at/by；
         op.student.course 13.subject_ids == 注册单科目集（并集有序）；
         batch/term 不变或更新为注册单值；state 仍 running
         （若用新学生无档案 → 自动建档 running + 学期 + 科目）
         edu.audit.log 新增；学生收到站内信（/my/messages 或 /my/notify 红点）
5. 王佐刷新 /subject/registration：状态=已通过；/my/courses 现出通过科目的课程卡
   （_subjects_for 学生分支读 subject_ids）；/my/courses/<subject> 可学（若已发布课次）
6. 教务驳回场景：另一单 rejected + reject_reason → 学生收到含原因通知；列表显示原因
7. 权限负例：学生 GET /registrar/… → 302 /my/home；普通教师/家长不可建档案；
   base.group_user 直连后台菜单仍可（原权限面）。
```

---

## 7. 实施清单（工程师执行顺序）
1. `models/registration.py`（_inherit 扩展 + action_enroll_approve/reject/_notify_student）
   + `models/__init__.py` 登记 + `models/notify_pref.py` 加事件 key。
2. `controllers/enroll.py`（学生目录/提交 + 我的申请增强 + 教务聚合/详情/set_state）
   + `controllers/__init__.py` 登记。
3. `controllers/lms.py` `_subjects_for` 学生分支改读 `student_course` 档案 `subject_ids`
   （保留 batch 空安全）。
4. `views/enroll.xml`（5 个模板）+ manifest data 登记；
   `views/approval_backend.xml` 加“选课审批”菜单 + 后台按钮换绑（xpath 替换，
   不删基座视图）；`views/edu_portal_templates.xml` 侧导航加学生“报课选科”与教师“选课审批”。
5. batch2.py：acad_hrefs 描述微调 + 可选新卡；`_approval_alerts` 加待批选课。
6. `custom_addons/edu_public`：/my-courses 页面 course 卡加“进入学习(/my/courses)”链（小改）
   或在门户内加新学生“我的课程”模板（按 reviewer 意见二选一，默认小改公开页+门户卡直链）。
7. security/ir.model.access.csv：无需给 portal 新增权限（控制器 sudo 读）；
   若给 elective/compulsory 写入用后台表单 → 按既有 faculty/backoffice ACL 已覆盖。
8. 本地验证：`docker compose exec web odoo -c /etc/odoo/odoo.conf -d edu19 -u edu_portal
   --stop-after-init`（EXIT=0）→ 各角色登录跑 §6 剧本 → `scripts/check_english.py`。
9. git commit（中文 conventional，如 feat(portal): 学生自主报课与教务审批）。

## 8. 验收标准（映射 task acceptance）
- [x] 设计文档覆盖学生报课流/教务审批流/状态机与权限/LMS 与课表联动/模型关系（§2/§3/§4）
- [x] 用户已确认默认裁决表 + 待拍板清单（§5）
- [x] 每个待决附默认（工程可先行）
- [x] 4 入口合并/保留建议（§4.1）
- [x] 权限矩阵（§4.3）
- [x] 基座 action_approve 缺陷规避（§1.2/§3.4）
