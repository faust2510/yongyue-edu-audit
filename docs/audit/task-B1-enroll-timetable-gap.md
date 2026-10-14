# 任务 B1 诊断：报课后 `/student/timetable` 仍只显示「神论」（王佐 · 生产）

> 诊断人：缺陷诊断子代理（B1）；时间：2026-09-18（DB 时间 UTC，用户时区 Asia/Shanghai）
> 范围：只读诊断。**未改任何业务代码、未改库、未动 `custom_addons/`**；生产仅 SELECT / 只读 ORM 探针；
> 未读取任何 `edu_telegram` 相关数据（红线）。

---

## 0. 结论速览

| 项 | 结论 |
|---|---|
| **判定** | **(A) 设计如此**（报课单仍 `submitted`，教务从未点「通过」⇒ 档案 `subject_ids` 未写 ⇒ 课表按「班级排课」口径自然不变）。**不是 BUG，不是数据问题。** |
| **一句话根因** | 报课单 SR0017 至今 `state=submitted`；而「把科目写进 `op.student.course.subject_ids`」的唯一入口是审批动作 `action_enroll_approve()`（`registration.py:133`，写入点 `:186/:190`）——**单据没批 = 档案没动 = 课表不变**。 |
| **为什么「只有神论」** | 学生课表 = **班级排课视图**（`scheduling.py:100-103` 只按 `batch_id` 查 `op.session`）。王佐的班 `batch 13 人文一年级` 本周（09-14 ~ 09-20）**全库只有 1 条课时**：9/14 周一 10:00–12:00「神论」；同班的「救恩论」排课从 **2026-11-16** 才开始。 |
| **附带发现（B 类缺口，非本次现象的必要条件）** | ① 设计文档称「课表读取 `subject_ids`」（`enroll-v2-design.md:153/189/291`），实现**只读 batch**（`scheduling.py:100-103`）——**即使审批通过，课表也不会出现所报的 21 门科目**：这 21 门在 `op.session` 里**排课数 = 0**；② `/student/subjects` 的「下一步四件事」写着「**① 看课表已更新**」（`views/study.xml:342`），是学生困惑的直接文案来源。详见 §6。 |
| **最小修复** | 本单**无需改代码**（行为符合设计）：让教务在 `/registrar/subject/approvals/19` 点「通过」即可写档案。若要消除误导，**1 行文案**（`study.xml:342`）即可；若要「报课→课表」真联动，属产品决策（§7）。 |

---

## 1. 调查对象（生产 edu19，只读）

| 对象 | id | 关键字段 |
|---|---|---|
| 学生 王佐 | `op.student` **11** | `partner 64`（tz=`Asia/Shanghai`）、`user 19`（`qnj2510798178@gmail.com`）、仅 `base.group_portal` |
| 在读档案 | `op.student.course` **13** | course 16 教育学士 / batch 13 人文一年级 / `state=running` / roll `BED2026-WZ001` |
| 报课单 | `op.subject.registration` **19**（SR0017） | `doc_type=subject_registration`、`state=submitted`、course 16 / batch 13 |
| 班 | `op.batch` **13** | 人文一年级，course 16，2026-06-23 ~ 2027-06-18 |

**读数（SQL）**

```
student_id|name|user_id|login
11|王佐|19|qnj2510798178@gmail.com

op_student_course:
id|course_id|course_zh|batch_id|batch_zh|state|academic_term_id|academic_years_id|roll_number|create_date|write_date
13|16|教育学士|13|人文一年级|running|1|1|BED2026-WZ001|2026-09-06 13:33:31|2026-09-14 02:38:16

op_subject_registration（全库仅此 1 条）:
id|name|course_id|course_zh|batch_id|batch_zh|state|doc_type|approved_at|approved_by|submitted_at|create_date
19|SR0017|16|教育学士|13|人文一年级|submitted|subject_registration|（空）|（空）|2026-09-17 06:53:54|2026-09-17 06:53:54
```

> `op_subject_registration` **全表只有 19 这一行**（`SELECT ... ORDER BY id` 只返回 1 行）——不存在「另一张已批的单」被课表漏读。

---

## 2. 端到端链路图（含逐环节真实状态）

```
[学生 王佐] ──POST /subject/enroll/save────────────► op.subject.registration(19)  state=submitted
   (06:53:54Z) enroll.py:271-282 create                │  payload = 21 门必修（compulsory 自动全带）
                                                        │  ★ 此步【不写】op.student.course.subject_ids
                                                        ▼
[教务/管理员] ──POST .../approvals/19/set_state──────► action_enroll_approve()   registration.py:133
   (从未发生 ❌) enroll.py:444 / 513                   │  sc = search(student, course, running)
                                                        │  sc.write({subject_ids:[(6,0,payload)]})  ← :190（写手）
                                                        │  （无档案则 create）                      ← :178-187
                                                        ▼
                                    op.student.course(13).subject_ids = {神论, 救恩论}
                                                        ├──► LMS /my/courses  ✅ 读 subject_ids（lms.py:27-30）
                                                        └──► 课表 /student/timetable ❌ 不读 subject_ids
                                                             = op.session[ batch_id = student_course().batch_id ]
                                                             （scheduling.py:100-103，单批口径）

[课表实际命中] batch 13 × 本周(09-14~09-20，Asia/Shanghai) = 1 条：session 353「神论」09-14 10:00-12:00
```

**断点位置：审批环节（`set_state`）从未被调用。** 其余各节读数如下。

---

## 3. 逐环节真实读数

### L1 报课提交（✅ 成功，读数为证）

`edu_audit_log`：

```
id|user_id|res_id|action|model|res_name|detail|create_date
37|19|19|报课提交|op.subject.registration|SR0017|学生 王佐 · 课程 教育学士 · 班级 人文一年级 · 必修 21 选修 0|2026-09-17 06:53:54.328853
```

生产容器访问日志（UTC）：

```
2026-09-17 06:53:54,389 ... 203.0.113.9 - - [17/Sep/2026 06:53:54] "POST /subject/enroll/save HTTP/1.1" 303
2026-09-17 06:53:55,177 ... 203.0.113.9 - - [17/Sep/2026 06:53:55] "GET /subject/registration?box=submitted&new_id=19 HTTP/1.1" 200
```

报课单 payload（`subject_compulsory_rel`，21 条；`op_subject_op_subject_registration_rel` = **0 条**）：

```
19|70 圣经神学导论   19|71 中国教会历史   19|73 初代教会历史   19|75 中世纪教会历史
19|78 基督论        19|80 实践神学导论   19|81 释经学        19|87 神学导论
19|90 阅读与通识    19|91 博物学        19|92 基督教与哲学   19|99 西方经典阅读
19|109 教育观       19|110 课程设计      19|111 差异化教学设计 19|117 阅读教学法
19|122 希腊文       19|123 拉丁文        19|124 希伯来文     19|125 古代汉语
19|138 毕业论文
```

### L2 教务审批（❌ 断点：从未审批）

| 证据 | 读数 |
|---|---|
| 单据状态 | `state=submitted`、`approved_at=NULL`、`approved_by=NULL` |
| 审计 | **全库没有任何 `选课审批` 记录**（`op.subject.registration` 相关审计只有 2 条：id34 批量审批「成功 0/失败 0/跳过 0/忽略 1」@09-17 01:51:30 —— 发生在报课（06:53:54）**之前**；id37 报课提交） |
| 访问日志 | 09-17 **07:12:23** `GET /registrar/subject/approvals` 200、**07:12:32** `GET /registrar/subject/approvals/19` 200 → **打开了 SR0017 详情页**，但**从未出现任何 `set_state` POST**（`grep set_state` 全窗口只命中 09-17 01:51 的 leave/grievance/subject 三个 *bulk* 路由） |
| 待办卡 | `safe_count('op.subject.registration',[state=submitted, doc_type=subject_registration])` = **1** ⇒ 教务工作台「待批选课 1」应可见（batch2.py:617-627） |

> 即：**审批详情页被打开过，但「通过/驳回」两个按钮都没有触发过服务端请求**。原因无法从日志判定（页面在 `diff_n=2` 时会显示「通过后将整体覆盖…其中 2 门将被替换」的红字提示，见 §6(3)）。

### L3 档案回写（❌ 未发生；且**不是**写错对象）

```
op_student_course_op_subject_rel（sc 13）:
op_student_course_id|op_subject_id|subject
13|56|神论
13|68|救恩论
```

| 对照项 | 读数 | 说明 |
|---|---|---|
| 档案现有科目 | **2** 门：56 神论 / 68 救恩论 | |
| 报课单 payload | **21** 门（YY-* 必修） | 与档案现科目**交集 = 0**（`SELECT count(*) ... WHERE op_subject_id NOT IN (payload)` = **2**） |
| 档案最后写时间 | `2026-09-14 02:38:16`（**早于**报课单 `2026-09-17 06:53:54`） | ⇒ 报课动作**没有**写档案 |

### L4 写手是谁 / 何时写（题目第 3 问）

| 动作 | 文件:行 | 说明 |
|---|---|---|
| **创建报课单**（学生侧） | `custom_addons/edu_portal/controllers/enroll.py:271-282` | 只写 `op.subject.registration`，`state='submitted'`；**不动档案** |
| **唯一写 `op.student.course.subject_ids` 的门户入口** | `custom_addons/edu_portal/models/registration.py:133` `def action_enroll_approve()`；写入点 **`:190`**（`sc.write({'subject_ids': [(6,0,subject_ids)], 'state':'running'})`）与 **`:186`**（无档案时 `sc_env.create({... 'subject_ids': ...})`，自动建档） | 覆盖式写入；`:167-171` 有「空 payload 且档案已有科目 → UserError 拒绝」防呆 |
| 触发它（单条） | `enroll.py:433-456`，调用 **`:444`** `rec.action_enroll_approve()` | 门禁 `current_faculty() or privileged_staff()`（`:437-439`） |
| 触发它（批量） | `enroll.py:461-530`，调用 **`:513`**（逐条 savepoint） | |
| 后台按钮路径（另一写手，门户不用） | `openeducat_erp/openeducat_core/models/subject_registration.py:64-82` `action_approve()` | 同样只 `write({'subject_ids': ...})`；**无档案会直接抛 ValidationError**（这就是门户另写 `action_enroll_approve` 的原因，见 `registration.py:6-9`） |

> **结论：写手存在、位置正确、对象正确**（按 `(student_id, course_id, state='running')` 命中 sc 13）。它没有出错，只是**从未被调用**。
> 交叉验证（本地 clone 有一条**已批**实例）：`op.subject.registration 536 / SR0513`（student 5、course 18、batch 8、`state=approved`、`approved_by=12`）→ `op.student.course 9` 的 `subject_ids = {选修课程}`（1 门，来自该单 elective）。说明「审批 → 写档案」这一段在真实数据上**是通的**。

### L5 课表查询（✅ 正常，且与报课无关）

学生视角取数（`custom_addons/edu_portal/controllers/scheduling.py:100-103`）：

```python
elif student:
    title, role = '我的课表', 'student'
    _, batch = student_course(student)          # main.py:47-55：取【第一条 running】档案
    domain.append(('batch_id', '=', batch.id if batch else 0))
```

- `student_course()`（`main.py:47-55`）：`search([(student_id,=,11),(state,=,'running')], limit=1)` → **sc 13 → batch 13**（王佐全库仅此 1 条档案：`SELECT ... GROUP BY student_id` 全表只有 student 11 一行）。
- 本周窗口（`week_utils.week_window_utc`，Asia/Shanghai）≈ **2026-09-13 16:00Z ~ 2026-09-20 16:00Z**。
- **SQL 复刻命中（1 条）**：

```
SELECT s.id, sub.name, s.start_datetime, s.end_datetime
FROM op_session s LEFT JOIN op_subject sub ON sub.id=s.subject_id
WHERE s.batch_id=13 AND s.start_datetime < '2026-09-20 16:00:00'
                  AND s.end_datetime  >= '2026-09-13 16:00:00';

id|name|start_datetime|end_datetime
353|神论|2026-09-14 02:00:00|2026-09-14 04:00:00     -- 本地(上海)= 09-14 周一 10:00–12:00，行 timing 15「10:00-12:00」
```

- **生产只读 ORM 探针**（`odoo shell`，复刻 `student_course()` + 同一 domain；事务内 `rollback()`，**残留=0**）：

```
ALL_SC [(13, 16, '教育学士', 13, '人文一年级', 'running')]
PICKED_SC 13 batch 13 人文一年级 subjects ['神论', '救恩论']
TODAY_LOCAL 2026-09-18 MONDAY 2026-09-14
WINDOW_UTC 2026-09-14 00:00:00 2026-09-21 00:00:00        # 探针身份 __system__(tz 空)=UTC 窗口
WEEK_SESSIONS_N 1
WEEK_SESSIONS [(353, '待定:神论:10:00AM-12:00PM', '神论', '2026-09-14 02:00:00', 15)]
REGS [(19, 'SR0017', 'submitted', 'subject_registration', 16, 13, '2026-09-17 06:53:54', 'False', False)]
REG_PAYLOAD [(19, [70,71,73,75,78,80,81,87,90,91,92,99,109,110,111,117,122,123,124,125,138])]
SAME_BATCH True 13 13                                     # 报课单目标班 == 档案班 ⇒ 通过也不会换班
TARGET_SUBJECTS_N 21
SESSIONS_OF_TARGET_SUBJECTS_N 0                            # ★ 这 21 门科目全库排课数 = 0
SESSIONS_OF_PROFILE_SUBJECTS_N 29
ALL_SESSIONS_N 216
RESIDUAL_SAME True 218 218                                 # 探针残留自证：改前=改后
```

（王佐 tz=`Asia/Shanghai` 的真实窗口另用 SQL 单独核对：同样 1 条。）

---

## 4. 「神论」是哪门课 / 哪个班？为什么只有它？

| 问题 | 读数 |
|---|---|
| 「神论」是什么 | `op.subject` **56**，`code=BTH-THE01`，`subject_type=elective`（注意：它是**选修**学科标签，但已挂在王佐的在读档案上） |
| 排在哪 | 全库 `op.session` 中「神论」共 **15** 条：**batch 13（人文一年级，course 16 教育学士）= 9 条**（2026-09-07 ~ 2026-11-09，每周一 timing 15 = 10:00–12:00）；batch 14（A1+A2+A3合班，course 14 神学学士科）= 6 条（与王佐无关） |
| 为什么本周只有它 | **batch 13 全库只有 18 条课时 = 神论 9 + 救恩论 9**；其中救恩论最早一条在 **2026-11-16**。本周（09-14~09-20）落在窗口内的只有 9/14 那节神论；上周(`w=-1`)同样只有神论，下周(`w=+1`)仍只有神论 |
| 与报课的关系 | **零关系**。课表按 `batch_id` 取 `op.session`，完全不读 `subject_ids`；王佐报的 21 门（YY-*）在全库 **0 条排课**（`SESSIONS_OF_TARGET_SUBJECTS_N = 0`；全库 216 条课时的科目只覆盖 `subject_id 52–69`） |

```
batch 13 课时明细（GROUP BY subject）:
subject_id|code|name|sessions|first_dt|last_dt
56|BTH-THE01|神论|9|2026-09-07 02:00:00|2026-11-09 02:00:00
68|BTH-SAL01|救恩论|9|2026-11-16 02:00:00|2027-01-11 02:00:00
```

---

## 5. 判定：**设计如此（A）** —— 逐条排除

| 假设 | 证据 | 结论 |
|---|---|---|
| **(A)** 报课单还是 `submitted`，教务没批 ⇒ 课表当然不变 | `state=submitted`/`approved_at` 空/无「选课审批」审计；访问日志显示详情页被打开但**无任何 set_state POST**；写手 `action_enroll_approve` 未执行；档案 `write_date`(09-14) 早于报课单(09-17) | ✅ **成立（本次现象的直接原因）** |
| **(B1)** 已批但课表不更新 | 全库**没有** `approved` 状态的报课单（唯一一条 19 是 `submitted`） | ❌ 不成立 |
| **(B2)** 审批只写单子、没回写学生档案 | 代码确实回写（`registration.py:186/190`），且本地 clone 的已批实例 `SR0513 → sc 9.subject_ids={选修课程}` 证明写入有效；本次是**没执行**而非**没写** | ❌ 不成立 |
| **(B3)** 课表查询口径漏了 | 王佐只有 1 条档案；即使口径改为「全部 running 档案 batch 并集」，命中集**完全相同**（仍是那 1 条神论）。口径确有可改进处（家长分支用并集、学生分支用单条），但**不是**本次现象的原因 | ❌ 不是本次原因（改进建议见 §6(4)/§7-R2） |
| **(C)** 数据问题（乱填导致 batch 错） | `batch 13.course_id=16` 与报课单 `course_id=16` 一致；`enroll_save` 有 `batch.course_id == course_id` 校验（`enroll.py:211-213`）；档案 batch/课程自洽 | ❌ 不成立 |

**结论：这是「报课 ≠ 排课」的认知差 + 「审批未执行」的流程状态，不是缺陷。**

---

## 6. 附带发现（B 类缺口 —— 建议单独立项，勿混进本单修复）

1. **文档与实现不符（口径承诺落空）**：`docs/plans/enroll-v2-design.md`
   - `:189` 「`op.student.course.subject_ids` 仍为事实源（**LMS/课表读取它**）」；
   - `:153` 「`/student/timetable`：按在读档案 batch 排课，通过后若改班级，周课表自动换班」；
   - `:291` 「LMS/**课表即时联动**」。
   实现侧：课表**只读 batch**（`scheduling.py:100-103`），LMS 才读 `subject_ids`（`lms.py:27-30`）。⇒ **SR0017 即使批准，课表也不会有任何变化**（目标班与档案班相同，且 21 门科目 0 排课）。
2. **UI 文案误导（学生困惑的直接来源）**：`custom_addons/edu_portal/views/study.xml:343-345`（文案文本「① 看课表已更新」当前在 `:345`；该文件在本轮诊断期间被并行任务改动过，**行号以文本为准**），报课后的「下一步四件事」第一件写着 **「① 看课表已更新」→ `/student/timetable`**。学生点进去只看到旧课表 ⇒ 必然报「报课了课表没变」。另 `views/enroll.xml:21-22` 已明示「由教务处审批后生效」，两处口径不一致。
3. **「整体覆盖」的连带效应（设计后果，需产品确认）**：审批详情页命中 `diff_n=2`（`enroll.py:424`），会显示「通过后将把该学生档案科目整体覆盖为本次申请的 21 门（其中 2 门将被替换）」（`views/enroll.xml:390-393`）。若真通过，档案里**会丢掉唯一有排课的神论/救恩论**，换进 21 门未排课科目 —— 此后 **LMS 显示 21 门新科目、课表仍只显示神论/救恩论**，两条口径彻底分叉。这很可能是审批人当天打开详情页后没有点「通过」的原因（无法证实，见 §8）。
4. **学生课表单批口径（潜在缺陷，当前未触发）**：学生分支只取**第一条 running 档案**的 batch（`scheduling.py:102-103`、`main.py:51-54`），而家长分支取**全部** running 档案的 batch 并集（`scheduling.py:106-113`）、停课判定 `_role_batch_context` 亦同（`scheduling.py:59-71`）。跨课程报课通过后会生成**第 2 条** `op.student.course`，届时学生课表只会显示其中一个班的课。**当前生产无多档案学生**（`op_student_course` 全表仅 1 行）。

---

## 7. 修复建议（**不实施**，交队长派单）

| 编号 | 内容 | 文件:行 | 风险 | 验证方式 |
|---|---|---|---|---|
| **R0（流程，无需改码）** | 让教务在 `/registrar/subject/approvals/19` 点「通过」（或驳回后让学生重选）；审批后 `/student/subjects`、`/my/courses` 立即变 | — | — | 审批后查 `op_student_course_op_subject_rel` 应为 21 行；`edu_audit_log` 出现「选课审批」 |
| **R1（文案，最小且推荐）** | 「① 看课表已更新」→「① 看班级课表（按已排课时）」，或在其下加一行小字「报课通过后科目进入『我的课程』；课表显示的是教务已排课时」 | `custom_addons/edu_portal/views/study.xml:345`（`<span>① 看课表已更新</span>`，1 行文案；行号以该文本为准） | 极低 | 本地 `-u edu_portal` → `/student/subjects` 文案断言；`scripts/check_english.py`；回归既有 smoke |
| **R2（口径对齐，建议）** | 学生分支改为「本人全部 `state=running` 档案的 `batch_id` 并集」，与家长分支同源；`_role_batch_context`（`:59-61`）同步 | `custom_addons/edu_portal/controllers/scheduling.py:100-103`（+ `:59-61`） | 中（改数据域） | 王佐页 200 且本周仍 1 条；造「双档案」夹具断言并集；家长视角回归不变 |
| **R3（产品决策，勿直接实施）** | 若确要「报课 → 课表出现新科目」，**必须二选一**：① 审批通过时同步生成 `op.session`（= 报课即排课，需排课规则/教师/时段）；② 课表口径改为 `subject_ids ∩ batch 排课`。**只改课表口径不够**——那 21 门科目根本没有课时可显示 | 需先出设计 | 高 | 须先定「课表表达什么」 |
| **R4（文档订正，低风险）** | 订正 `enroll-v2-design.md:189`（及 `:153` 的措辞）：课表读 **batch**，不读 `subject_ids` | `docs/plans/enroll-v2-design.md` | 极低 | 文档评审 |

> ⚠️ 给实现者的红线：`registration.py:167-171` 的「空 payload 防呆」不得放松；不要为了「让课表有课」而在审批时伪造 `op.session`。

---

## 8. 未验证项（如实标注）

1. **未用浏览器登录王佐复现**（无凭据）；课表读数 = 生产 SQL 复刻 + 生产只读 ORM 探针，与 `scheduling.py` 逐行同口径，但**未取页面截图/DOM**。
2. 生产 ORM 探针的运行身份是 `__system__`（`tz` 为空 → 按 UTC 计算周窗口）；王佐 tz=`Asia/Shanghai` 的窗口已用 SQL 单独核对（结论一致：窗口内 1 条），但**未以王佐身份重跑探针**。
3. **09-17 07:12:32 打开 SR0017 详情的人是谁、为何没点「通过」**：日志只能证明「打开了详情页」且「**从未提交任何 `set_state`**」，不能证明原因（可能与 `diff_n=2` 的「将替换 2 门」红字提示有关，属推测）。
4. **审批按钮是否存在前端静默失败**（例如 JS/CSRF 导致点击无请求）未验证：无 POST 记录既可能是「没点」，也可能是「点了没发出」。若队长要排除，需人工用管理员账号打开 `/registrar/subject/approvals/19` 点一次（**会写库**，须由队长决定并授权）。
5. 本地 clone **无王佐数据**（本地学生为 王小明 id 5 等夹具），故本地仅用于口径验证（`student_course()` 单档案行为 + 已批实例 `SR0513` 的写入证据），**未做数据比对**。
6. 未排查 `op.session` 的生成链路（`/timetable/bulk`、周期排课）为何没有为这 21 门科目排课——影响 R3 的可行性，需排课侧另行确认。
7. 未读取任何 `edu_telegram`/`edu_tg_bind` 数据与配置（红线）。

---

## 附录 A：复核命令（可直接粘）

**A1 生产只读 SQL（不写库）**

```bash
ssh prod-host "docker exec -i edu19-prod-db-1 psql -U odoo -d edu19 -X -A -F'|' -P pager=off" <<'EOSQL'
SET statement_timeout='20s';
-- ① 档案与科目
SELECT sc.id, sc.course_id, sc.batch_id, sc.state, sc.write_date
FROM op_student_course sc WHERE sc.student_id=11;
SELECT r.op_student_course_id, r.op_subject_id, sub.name
FROM op_student_course_op_subject_rel r JOIN op_subject sub ON sub.id=r.op_subject_id
WHERE r.op_student_course_id=13;
-- ② 报课单
SELECT id, name, state, doc_type, approved_at, approved_by, submitted_at
FROM op_subject_registration WHERE student_id=11;
-- ③ 课表实际命中（batch 13 × 本周，Asia/Shanghai 窗口）
SELECT s.id, sub.name, s.start_datetime FROM op_session s
LEFT JOIN op_subject sub ON sub.id=s.subject_id
WHERE s.batch_id=13 AND s.start_datetime < '2026-09-20 16:00:00'
                  AND s.end_datetime  >= '2026-09-13 16:00:00';
-- ④ 21 门报课科目全库排课数（应为 0）
SELECT count(*) FROM op_session WHERE subject_id IN (
  SELECT subject_id FROM subject_compulsory_rel WHERE register_id=19);
EOSQL
```

**A2 生产只读 ORM 探针（事务内 rollback，自证残留=0）**

```bash
ssh prod-host 'docker exec -i edu19-prod-web-1 odoo shell -d edu19 --no-http --log-level=error --db_host=db -r odoo -w odoo' <<'PYEOF'
from odoo.fields import Datetime as Dt
from odoo.addons.edu_schedule.models.week_utils import monday_of, week_window_utc
from datetime import datetime
stu = env['op.student'].browse(11)
sc = env['op.student.course'].search([('student_id','=',stu.id),('state','=','running')], limit=1) \
     or env['op.student.course'].search([('student_id','=',stu.id)], limit=1)
print('PICKED_SC', sc.id, sc.batch_id.id, sc.batch_id.name, sc.subject_ids.mapped('name'))
monday = monday_of(Dt.context_timestamp(env.user, datetime.utcnow()).date())
ws, we = week_window_utc(monday, env.user.tz or 'UTC')
ses = env['op.session'].search([('batch_id','=', sc.batch_id.id or 0),
        ('start_datetime','<', Dt.to_string(we)), ('end_datetime','>=', Dt.to_string(ws))])
print('WEEK_SESSIONS', [(s.id, s.subject_id.name, str(s.start_datetime)) for s in ses])
print('TARGET_SESSIONS', env['op.session'].search_count([('subject_id','in', env['op.subject.registration'].browse(19)._subject_payload())]))
before = env['op.student.course'].search_count([]) + env['op.subject.registration'].search_count([])
env.cr.rollback()
after = env['op.student.course'].search_count([]) + env['op.subject.registration'].search_count([])
print('RESIDUAL_SAME', before == after, before, after)
PYEOF
```

## 附录 B：关键原始行（审计 / 访问日志）

```
edu_audit_log（op.subject.registration 相关全部 2 条）
34|12|选课批量审批|2026-09-17 01:51:30|批量通过：成功 0 / 失败 0 / 跳过 0 / 忽略 1     ← 发生在报课之前
37|19|报课提交|2026-09-17 06:53:54|学生 王佐 · 课程 教育学士 · 班级 人文一年级 · 必修 21 选修 0

edu19-prod-web-1（UTC）
2026-09-17 06:53:54 "POST /subject/enroll/save" 303   ← 报课（203.0.113.9）
2026-09-17 06:53:55 "GET /subject/registration?box=submitted&new_id=19" 200
2026-09-17 06:54:12 "GET /my/courses" 200             ← 学生看「我的课程」
2026-09-17 06:54:14 "GET /my/courses/56" 200          ← 神论
2026-09-17 07:12:23 "GET /registrar/subject/approvals" 200        ← 教务打开待批列表（203.0.113.9）
2026-09-17 07:12:32 "GET /registrar/subject/approvals/19" 200     ← 打开 SR0017 详情
（此后直到 2026-09-18 01:22 无任何 set_state 请求；无「选课审批」审计）
```
