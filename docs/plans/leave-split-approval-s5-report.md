# S5 交付报告：请假分级审批的测试与门禁
> **状态**：`归档` ｜ **主题**：`请假审批门禁` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「未 commit」，实际已于 `2fe14e9` 提交（2026-09-26 核对发现）。正文未改动。

> 交付人：S5（测试与门禁）　日期：2026-09-24　本地 clone（edu19，docker edu19-clone）
> 设计稿：`docs/plans/leave-split-approval-design.md` §9.3（验收命令闭环）/ §9.4（A1–A14）
> 上游：S1 数据层 / S2 模型逻辑 / S3 控制器 / S4 视图（四份均已交付）
> **生产未动、未 commit**（只 `git add` 我自己的 4 个文件，见 §8）

---

## 1. 新建测试文件 + 用例清单 + 实际输出

**新建：`tests/smoke/leave_split_approval.py`**（935 行；`--selftest` / `--model-only` / 全量三档）

| 断言 | 落点 | 本次实测读数（摘） |
|---|---|---|
| A1 结构 | 注册表 / 列 / UNIQUE / **11 个冻结签名** / RouteResult 四字段 | `edu_leave_transfer_transfer_once` 唯一索引在；签名 missing=无 |
| A2 有班主任 | 班 8 设 `homeroom_teacher_id=11` → 门户建 2 天单 | state=request、first=11、second=空、route_note 空 |
| A3 无班主任 | 清空该字段 → 再建 2 天单 | first=2 ∈ 教务处组[2,12]；route_note=「未设班主任，已转教务处」 |
| A4 学生未分班 | 学生 7（无 `op.student.course.batch_id`）建单 | first=2；route_note=「该生未分班，已转教务处」 |
| A5 4 天 | 一级通过后 `pending_second` | state=request→pending_second、second=2 ∈ 教务处组 |
| A6 3 天（边界） | 一级即终 | 2026-09-24~09-26 days=3 → approved、second 空 |
| A7 转交一次 | `/leave/transfer` → 12 | first=12、transfer 行=1、「请假审批转交」审计 +1、三方通知 3 条 |
| A8 **负向** | 转交后原审批人 POST `/leave/set_state` | 303 且 **state/快照/write_date 逐字段未变**、**无新 audit 行** |
| A9 **负向** | 第二次转交（HTTP）+ 直接 ORM 插重复行 | 转交行仍=1；直接插行 → **UniqueViolation**，行数 1→1 |
| A10 配额 | 事假累计 22 +1 天 >5 | over_quota=True → 仍进 pending_second |
| A11 事后补假 | 门户昨天（422、不落库）/ 后台同款单 | rows 19→19 hit=0；后台 id=465 backfilled=True |
| A12 病假证明 | 2 天无证明（422）/ 1 天对照 / 2 天口头证明 | hit=0；1 天 proof_required=False；oral 放行且审批后 `oral_proof_confirmed_by_id=12` |
| A13 **负向** | 实践周单据 | edu.leave 无任何折算/调休字段；日期逐字未变（09-24~09-24 days=1） |
| A14 回归 | cron 39 文案 + 幂等 | body 含「当前应批人：Administrator（未设班主任，已转教务处）」；二次跑 n=0 |

`--selftest`（不连站点，证明尺子准）：**16 PASS / 0 FAIL**；其中 3 条是"尺子本身"的断言 ——
含头含尾 3 天 vs 4 天、证明规则 1 天 vs 2 天、route_note 正/反例、负向尺子 `diff_keys`、
折算字段模式抓可疑字段，以及**离线核对 S2 源码里 11 个冻结签名逐个有 `def`**（不发明方法名）。

### 全量原始输出（`python3 tests/smoke/leave_split_approval.py` → **46 PASS / 0 FAIL / exit 0**）

```
=== 请假分级审批冒烟（设计稿 §9.4 A1–A14）· 2026-09-24 ===
目标 http://localhost:8069 / db edu19 / 容器 edu19-clone-db-1
夹具：stu=8 fac=11 bo=12 admin=2｜教务处组=[2, 12]｜系统组=[2]
     学生(有班)=5 王小明 → 班 8（班主任现值 0）；学生(未分班)=7 张同学【演示】；学期=第一学期
  ---- A1 注册表 / 列 / 唯一约束 / 冻结签名
  [PASS] A1    edu.leave.transfer 在注册表                          | table=edu_leave_transfer
  [PASS] A1    op_batch.homeroom_teacher_id 字段存在（ORM）           | table=op_batch
  [PASS] A1    op_batch.homeroom_teacher_id 列存在（DB）             | information_schema 命中=1
  [PASS] A1    edu_leave_transfer 有唯一索引（UNIQUE(leave_id, stage)） | unique_index=edu_leave_transfer_pkey,edu_leave_transfer_transfer_once
  [PASS] A1    S2 冻结签名 11 个全部可调用（含别名 transfer）                  | missing=无
  [PASS] A1    RouteResult 四字段与设计稿 §3.2 逐字一致                    | 实际=['first_users', 'second_users', 'need_second', 'fallback_reason']
  ---- A2 有班主任：op_batch(8).homeroom_teacher_id := faculty@local(11)
  [PASS] A2    门户建 2 天单成功（303 → ?box=submitted）                 | code=303 loc=/my/time_off?box=submitted
  [PASS] A2    state=request 且 2 天（含头含尾）                        | state=request days=2
  [PASS] A2    first_approver_id = 班主任本人（faculty@local=11）      | first=11
  [PASS] A2    second_approver_id 空（2 天不需要二级）                   | second=0
  [PASS] A2    route_note 为空（有班主任 ⇒ 无兜底文案）                      | route_note=''
  [PASS] A5    4 天单：一级通过后 state=pending_second                  | code=303 state=request→pending_second
  [PASS] A5    second_approver_id ∈ 教务处组 [2, 12]                | second=2
  [PASS] A5    4 天 = 4（含头含尾、自然日）                                | 2026-09-24 ~ 2026-09-27 → days=4
  [PASS] A6    3 天 = 3（边界值，含头含尾）                                | 2026-09-24 ~ 2026-09-26 → days=3
  [PASS] A6    3 天单：一级通过后直接 approved（不进二级）                      | code=303 state=request→approved second=0
  [PASS] A7    转交一次 ⇒ first_approver_id 变成转入人（bo=12）            | code=303 first=12
  [PASS] A7    edu_leave_transfer 有且仅有 1 行                      | rows=1
  [PASS] A7    edu_audit_log 新增「请假审批转交」1 条                      | before=9 after=10
  [PASS] A7    三方通知落库（正文含单号 SLR000085）                          | rows=3
  [PASS] A8    负向：转交后原审批人 POST ⇒ 303 且 state 未变                 | code=303 state=request→request loc=/leave/approvals
  [PASS] A8    负向：该单逐字段「没发生」任何写入（含 write_date）                  | changed=无
  [PASS] A8    负向：无新 audit 行（全局 / 单条两口径）                        | 全局 65→65；单条 0→0
  [PASS] A9    负向：第二次转交（HTTP）⇒ 303 且转交行仍为 1                     | code=303 rows=1→1 first=12
  [PASS] A9    负向：直接 ORM 插重复行撞 UNIQUE(leave_id, stage)          | raised=UniqueViolation before=1 after=1
  [PASS] A3    无班主任 ⇒ first_approver_id ∈ 教务处组 [2, 12]          | first=2
  [PASS] A3    route_note 含「未设班主任，已转教务处」                        | route_note='未设班主任，已转教务处'
  [PASS] A4    学生未分班 ⇒ 同「无班主任」分支（first ∈ 教务处组）                  | first=2 batch=0（学生=7 张同学【演示】）
  [PASS] A4    route_note 含「该生未分班，已转教务处」                        | route_note='该生未分班，已转教务处'
  [PASS] A10   事假学期累计 22.0 + 本单 1 天 > 5 ⇒ over_quota=True       | used=22.0 days=1 over_quota=True
  [PASS] A10   即使只有 1 天，一级通过后仍进 pending_second                  | code=303 state=request→pending_second
  [PASS] A11   负向：门户 date_from < today ⇒ 422 且**不落库**           | code=422 rows 19→19 hit=0
  [PASS] A11   后台例外通道同款单 ⇒ 成功且 backfilled=True                  | id=500 backfilled=True
  [PASS] A12   负向：病假 2 天无任何证明 ⇒ 422 且**不落库**                    | code=422 rows 20→20 hit=0
  [PASS] A12   对照：1 天病假不传证明也放行（proof_required=False）            | code=303 proof_required=False
  [PASS] A12   填 oral + 证明人 ⇒ 放行且 proof_required=True           | code=303 days=2 proof_required=True kind=oral
  [PASS] A12   审批人点通过 ⇒ oral_proof_confirmed_by_id = 审批人（12）    | code=303 confirmed_by=12
  [PASS] A13   负向：edu.leave 上不存在任何折算 / 调休 / 拼假字段                | 命中=无（模式=makeup,make_up,compensat,convert,exchange,shift,swap,defer,reschedul,holiday,调休,拼假,折算）
  [PASS] A13   负向：实践周单据日期逐字未变（无任何折算改写）                          | 2026-09-24 ~ 2026-09-24 days=1 long_absence=False
  [PASS] A13   负向：实践周单据的 state 未被折算逻辑改写                         | state=request
  [PASS] A14   cron 39 提醒文案含「当前应批人」                             | n=1 body=【审批超时提醒】请假申请 SLR000088（王小明，2026-09-24 ~ 2026-09-25）已超过 48 小时未处理，请尽快审批。
当前应批人：Administrator（未设班主任，已转教务处） ~~ 【审批超时提醒】请假申请 SLR000088（王小明，2026-09-24 ~ 2026-09-25）已超过 48 小时未处理，请尽快审批。
当前应批人：Administrator（未设班主任，已转教务处）
  [PASS] A14   提醒后已打 escalated_at（幂等去重标记）                       | escalated_at=2026-09-24 11:04:07
  [PASS] A14   第二次跑 ⇒ 该单不重复提醒（新消息数 = 0）                         | second_notified=0（n=0）

收尾：本次建单 10 张 → leftover=0；班 8 班主任现值=0
   homeroom_now           0
   leftover_leaves        0
   leftover_msg           0
   leftover_transfer      0
  [PASS] CLEAN 夹具归还：本次建的每一张单都查不到（leftover = 0）                  | leaves=0 transfer=0 msg=0
  [PASS] CLEAN op_batch 班主任字段已还原为 NULL（「上线当天 100% 走教务处」的前提）     | homeroom_now=0
  [PASS] COVER A1–A14 全部执行过（无静默跳过）                              | missing=无

== leave_split_approval：46 PASS / 0 FAIL ==
```

覆盖率自查：`A1–A14 全部执行过（无静默跳过）` PASS；收尾 `leftover = 0`（10 张夹具单逐 id 复查）
+ `op_batch(8).homeroom_teacher_id` 已还原 NULL。
---

## 2. 两条既有夹具的 exact diff + 重跑原始输出

### 2.1 tests/smoke/F_roles_smoke.py（家长 sick 单：2 天 → **1 天**）

```diff
@@ -477,8 +477,14 @@ def parent_leave(pg):
     if ok_page:
         form.locator("select[name='leave_type']").select_option("sick")
         form.locator("input[name='date_from']").fill(TODAY.strftime("%Y-%m-%d"))
-        form.locator("input[name='date_to']").fill(
-            (TODAY + datetime.timedelta(days=1)).strftime("%Y-%m-%d"))
+        # ⚠ 时长 = **1 天**（2026-09-24 起新规则《请假条例》二·3：**病假 ≥2 天必须
+        #   提交证明**（文件或口头证明）；本夹具是 sick、且不带任何证明字段）。
+        #   原来是「今天~明天」= 2 天，会撞新规则的 create 校验（门户侧 422、不落库），
+        #   与本夹具真正要测的东西（**家长代提**这条角色路径）无关，故缩到 1 天 ——
+        #   断言强度不减：页面回执 + edu.leave 新增且 state=request 一条不变。
+        #   新规则本身由 tests/smoke/leave_split_approval.py 的 **A12** 专门覆盖
+        #   （2 天病假无证明 ⇒ 拒绝；1 天病假 ⇒ 放行；口头证明 ⇒ 放行并留确认人）。
+        form.locator("input[name='date_to']").fill(TODAY.strftime("%Y-%m-%d"))
```

### 2.2 tests/smoke/course_rep.py（10 处请假夹具：时长 + 日期 + 班主任）

⚠ **这里比队长清单多修了两件事**（原清单只点了 668/675/769/803 的「2 天 → 1 天」）：

| # | 冲突 | 证据 | 处置 |
|---|---|---|---|
| ① 时长 | sick 2 天无证明 ⇒ 门户 422 | 与队长清单一致 | sick 夹具统一 **1 天**（668/675/769；803 本来就是 1 天） |
| ② **日期** | 全部 2026-06-xx 都在**过去** ⇒ 撞 §7.5「禁止事后补假」硬拒（门户 422、**不落库**） | 基线实测：line 670 IndexError（建单失败 ⇒ new_leaves() 空 ⇒ 整脚本崩） | 新增 lvdate(n) = 今天+n，**10 处**全改未来日期 |
| ③ **授权** | 新判据 user == first_approver_id or privileged_staff()（§8.1）。夹具班**没有班主任** ⇒ 一级应批人 = 教务处组，普通教师不是应批人 ⇒ POST /leave/set_state 被 fail-closed 挡住 | 第二次跑 3 条红：N2e（state 仍 request）、P4-faculty（kind=NULL）、P4d（kinds=admin,registrar,student_rep） | 新增 set_homeroom(夹具班, faculty@local)（= §3.3「老师到位后只填数据即生效」），**三条断言一字未改** |

> **断言强度自查**：没有删除、没有放宽任何断言 —— N2e / P4-faculty / P4d 仍要求
> 「教师/教务/管理员各自单独批成功且记自己的 approver_kind」，只是把「教师必须被授权」
> 这一新规则**如实**补进夹具；「无班主任时教师批不动」这条新行为由新脚本的 A3 覆盖。

```diff
@@ -510,6 +510,39 @@  (submit_leave 之后新增夹具工具)
+ LV_TODAY = datetime.date.today()
+ def lvdate(days):
+     """请假夹具日期：今天 + days 天（保证不触发「事后补假」硬拒）。"""
+     return (LV_TODAY + datetime.timedelta(days=days)).isoformat()
+ def set_homeroom(batch_id, uid):  # 只填数据、不改代码：班主任 = 任课老师

@@ 10 处 submit_leave（逐处）
- submit_leave(rep_s,  'sick', '2026-06-10', '2026-06-11', ...)   # 2 天 + 过去
+ submit_leave(rep_s,  'sick', lvdate(1),  lvdate(1),  ...)        # 1 天 + 未来
- submit_leave(mate_s, 'sick', '2026-06-10', '2026-06-11', ...)   # 对照单
+ submit_leave(mate_s, 'sick', lvdate(1),  lvdate(1),  ...)
- submit_leave(out_s,  'sick', '2026-06-12', '2026-06-12', ...)   # 以下 7 处只改日期
+ submit_leave(out_s,  'sick', lvdate(2),  lvdate(2),  ...)
  … legal lvdate(3) / other lvdate(4) / sick lvdate(5)
  … sick lvdate(6)（原 06-20~21 = 2 天 → 1 天）/ lvdate(7+i) / lvdate(10) / lvdate(11)

@@ run_all()：探活 C00b 绕过本机 macOS 系统代理（原来稳定 502、白等 100×3 秒）
- code = requests.get(BASE + '/web/login?db=' + DB, ...)
+ _probe = requests.Session(); _probe.trust_env = False
+ code = _probe.get(BASE + '/web/login?db=' + DB, ...)

@@ run_all()：第一张假单之前，给夹具班填班主任
+ hr = set_homeroom(batch, tea_uid)
+ check('HR0', '夹具班已设「班主任 = faculty@local」（分级审批的一级应批人前提）', ...)
```

本机实测（代理证据）：`裸 requests.get → 502`；`Session(trust_env=False) → 302`。

### 重跑原始输出

**改前（基线，exit=1）**
```
  [FAIL] C00b           web 就绪（带库名登录页） | code=502 tries=100
Traceback (most recent call last):
  File ".../tests/smoke/course_rep.py", line 670, in run_all
    lid_self = new_leaves(base['leave'])[-1]
IndexError: list index out of range
[exit=1]
```

**改后（第三跑，exit=0）**
```
  [PASS] HR0            夹具班已设「班主任 = faculty@local」（分级审批的一级应批人前提）
  [PASS] N2e            N2 老师批它 → 成功且 approver_kind 不是 student_rep
  [PASS] P4-faculty     P4 faculty 可单独批（不串行等待）→ kind=faculty
  [PASS] P4d            P4 三种身份都记了审批人（faculty / registrar / admin 各一行）
  [PASS] CLEAN          夹具归还：本次夹具的每个 id 都查不到（leftover = 0）
== course_rep: 84/84 PASS == (course_rep_results.json)
[exit=0]
```

**F_roles_smoke.py 重跑（RESULT PASS=11 FAIL=1，exit=1）**
```
[PASS] t9 家长为孩子提交请假（已造数） :: 页面=200, saved=True     ← 本次修的就是它
[SKIP] t5 教师请假审批（批准 t9 冒烟单） :: 页面=200, 待审前=12, 列表含该单=True, 点击批准=True  ← 与改前同口径（t70 起本就是 SKIP）
[FAIL] t12 管理员后台菜单探活（odoo shell） :: 6/6 行返回, 全部有效=False  ← 与本功能无关，见下
[自清] 作业 leftover=0 / 公告 leftover=0 / 请假 leftover=0 / 当日考勤表=1 -> OK
```

t12 明细（原始）：`在线课程(menu_edu_lms_root) menu=576 action=NO_ACTION`、
`日常管理(menu_edu_welfare_root) menu=543 action=NO_ACTION`；DB 实测这两条 `ir_ui_menu.active=f`
（2026-09-17 菜单收口的既定结果，code-map §4.1 明写「543 日常管理已停用」）。
而 `教务审批(menu_edu_approval_root) menu=497 … res_model=edu.leave 有效=True` ——
**请假自己的菜单是好的**；t12 的期望清单属菜单收口工作面，本次未改（不越界）。
---

## 3. check_english 路由登记 diff + 登记前后输出

登记位置：scripts/check_english.py 的 EXEMPT_ROUTES（照既有 (路径, 角色) → 理由 写法）。

~~~diff
@@ EXEMPT_ROUTES = {
+    # 请假分级审批（S5 登记，2026-09-24）：**家长身份**的 /my/time_off 是 S3 的
+    # **有意分流**，不是改名后的替身 —— 家长既不是学生（不套学生单），也不是教职
+    # （家长不算教职单，判据见 leave-split-approval-design.md §5.3），他的入口归
+    # 孩子的请假页 /my/child（S3 报告 §6-1 与 batch3.py 的门禁跳转注释同款）。
+    # 学生/教师/教务/系统身份下该路由仍是 200（照常扫描英文）。**不要**改成 200。
+    ('/my/time_off', 'parent'): '家长身份 → 303 /my/child（S3 有意分流：家长不套学生单/'
+                               '教职单，入口归孩子页；其余角色仍 200）',
     ('/apps', '*'): '门户/匿名 → 303 /my/home；内部用户 200（t4 三层落点设计）',
~~~

（git diff --stat：scripts/check_english.py | 7 +++++++，1 file changed, 7 insertions）

### 登记前（exit=2）

~~~
  /my/time_off                     303 ROUTE-BAD 非 200 且未登记 → /my/child
parent      must-fix 0    brand 0    白名单 57   数据 69    主题 110  路由违规 1   夹具残留 0  （路由 69 条）
TOTAL must-fix = 0 条 / brand = 0 条 / **路由状态违规 = 1 条** / **夹具残留 = 0 条**
[exit=2]
~~~

### 登记后（exit=0）

~~~
  /my/time_off                     303 REDIR -> /my/child   [登记：家长身份 → 303 /my/child（S3 有意分流：家长]
parent      must-fix 0    brand 0    白名单 57   数据 69    主题 110  路由违规 0   夹具残留 0  （路由 69 条）
TOTAL must-fix = 0 条 / brand = 0 条 / **路由状态违规 = 0 条** / **夹具残留 = 0 条**（其余合计 1710 条，不计失败）
自证：REVISION=v3.7 · 指纹 7361db98 · 断言 43 条 · 运行时刻 2026-09-24T19:04:53+08:00
[exit=0]
~~~

--selftest 复跑：**通过**，selftest_cases 实际 43 / 声明 43（指纹随文件变化为 7361db98，符合设计「运行时现算」）。

---

## 4. 清场前后计数（S3 遗留测试单）

口径：reason 以 S3 开头（含 S3- 与 S3␠ 两种写法；覆盖 S3 冒烟 / S3-TYPE- / S3-EVID2 / S3-FINAL / S3-REPORT 各代际）。

~~~
=== BEFORE ===   leaves_total=32   transfers_total=5
 候选 19 行：372(S3 冒烟-学生单) 373(S3 冒烟-教职单) 374(S3-L1 两日单-待转交) 375(S3-L2) 376(S3-L3)
            377(S3-L4) 385(S3-L6) 439~445(S3-TYPE-* / S3-EVID2) 446~450(S3-EVID2 / S3-FINAL / S3-REPORT)
=== DELETE ===   DELETE 19
=== AFTER  ===   leaves_total=13   transfers_total=0   s3_left=0
（edu_leave_transfer 5 行随 ondelete=cascade 一并消失：374/375/445/447/449 各 1 行）
~~~

**关于 374/375**（队长：保留 S2 报告点名的两张真实单，**除非确认它也是 S3 前缀**）——
已确认**就是** S3 前缀，故按规则清理。证据：

| 证据 | 原始读数 |
|---|---|
| 单据 reason | 374 = S3-L1 两日单-待转交；375 = S3-L2 两日单-留作原审批人仍有待办 |
| 转交行 reason | 374 的 edu_leave_transfer 行 = 「S3 冒烟：转交给教务」（create_date 10:03:41） |
| 审计（保留，append-only） | 2881 转交 / 2882 一级通过 / 2891+2892 销假（S3 冒烟：已按期返校，完成实践记录）/ 2904+2905 销假（已返校，附行程与收获）—— 全部带 S3 冒烟字样 |
| 时间窗 | 374 的全部留痕落在 10:03:41–10:04:16，与 S3 冒烟同一分钟窗口 |

> 审计行**一条未删**（22 条 model=edu.leave 的 S3 相关行完整留在库里），
> 所以这两张单可像 S2 那次一样「按审计逐字重建」；若队长要求恢复，逐字脚本就是这张审计表。

---

## 5. cron 43（请假销假逾期提醒）首次执行 + 幂等 + 副作用回滚

### 5.1 记录读数（ir_cron id=43 / 服务动作 818）

~~~
id=43  cron_name=edu_portal: 请假销假逾期提醒   active=t   interval=1 days
nextcall=2026-09-25 09:51:04   lastcall=2026-09-24 09:53:02
failure_count=1   first_failure_date=2026-09-24 09:53:02   ← S2 落地前那次 AttributeError 的历史遗留
ir_actions_server_id=818   code: model._cron_return_overdue()
~~~

（failure_count / first_failure_date 是 S2 落地前的历史值，不是本次产生的，故未回改。）

### 5.2 执行（真 cron 通路 ir.cron(43).method_direct_trigger()，非直调方法）

~~~
调用前 候选（approved + date_to<today + 未销假 + 未提醒）：[458]   ← 本次夹具（见 5.4）
2026-09-24 10:44:50,349 INFO edu19 odoo.addons.base.models.ir_cron:
    Job 'edu_portal: 请假销假逾期提醒' (43) starting
2026-09-24 10:44:50,409 INFO edu19 odoo.addons.base.models.ir_cron:
    Job 'edu_portal: 请假销假逾期提醒' (43) fully done (#loop 1; done 0; remaining 0; duration 0.06s)
trigger 返回 True
~~~

副作用（执行后读数）：

~~~
leave 458  return_overdue_alerted_at = 2026-09-24 10:44:50
edu_message 新增 2 条（event_key=leave_return_overdue）：
  id=2326 → admin            【销假提醒】请假申请 S5CRON1（王小明，2026-09-10 ~ 2026-09-11）已到期但尚未销假，请提醒学生提交「行程及实践收获」并确认销假。
  id=2327 → backoffice@local （同上正文）
候选（再查）= []（已被标记 ⇒ 不再被扫到）
~~~

### 5.3 幂等性（第二次执行命中 0 条）

~~~
第二次（payload 直调，可拿到返回条数）：return = 0；新消息 = 0；return_overdue_alerted_at 未变（10:44:50）
~~~

### 5.4 副作用如何清回原状

本次**先跑了一次空扫描**（当时唯一候选 leave 14 是 active=f 归档行 ⇒ 被 ORM 的 active_test 过滤掉，
payload 返回 0、无任何副作用），再**造了一张夹具单**才把「扫描 → 通知 → 打标」这条链路真正跑通 ——
否则「首次执行」只会命中 0 条，什么都证明不了（原始读数 scan_before=0）。

清回动作与校验：

~~~
① 删夹具单：edu_leave.browse(458).unlink()          → 该行的 return_overdue_alerted_at 随行消失
② 删本次产生的站内信：edu_message id ∈ {2326,2327} → deleted=2
③ 复核（裸 SQL）：alerted_rows=0 / my_msgs=0 / msg_max=2324（回到跑之前）/ cron_fixture=0
④ cron 记录本身：lastcall / nextcall / failure_count 未被 method_direct_trigger 改动
   （仍 09:53:02 / 2026-09-25 09:51:04 / 1）
~~~

**顺带发现（观察项，未修）**：扫描域 state=approved + date_to<today + return_confirmed_at=False +
return_overdue_alerted_at=False 跑在 ORM 默认 active_test=True 之下 ⇒ **归档（active=False）
的请假单永远不会被提醒**。本库 leave 14（SLR000003）正是这种行。是否要覆盖归档单 → 由队长定。

---
---

## 6. batch2.py 的 5 项 L2 缺失：独立归因（结论 + 证据）

**结论：既不是「本次请假功能引入的回归」，也不是「既有未提交改动」——
它是零丢失门禁的 L2 扫描目标在 H-1 改版后失配，读到的是 admin 视角而非学生视角；
5 张卡对学生一张不少，全部好端端在 /my/home 上。batch2.py 一行未改（不在我范围）。**

### 证据链（全部可复跑）

**(1) 工作区里的 batch2.py 与 HEAD 逐字相同 —— 不存在"未提交改动在生效"**

~~~
$ git rev-parse HEAD:custom_addons/edu_portal/controllers/batch2.py  -> 67fa8b1929ca57adf8f0ef4bca37fa97dcf890f5
$ git rev-parse :custom_addons/edu_portal/controllers/batch2.py      -> 8225bfea95cc453bbebc82e9d6a864ae14430e49
$ git diff HEAD -- custom_addons/edu_portal/controllers/batch2.py    -> （空）
$ git diff --cached --stat -- .../batch2.py   -> 1 file changed, 3 insertions(+), 10 deletions(-)
$ git diff --stat -- .../batch2.py            -> 1 file changed, 10 insertions(+), 3 deletions(-)
~~~

- HEAD 到工作区 = 空（两侧哈希都是 67fa8b1）；本地容器挂载的是**工作区**，所以跑的就是 HEAD 代码。
- 索引里那 3+/10- 与工作区的 10+/3- **正好互为逆操作**：索引里躺着的是 commit 78aa11d
  （财务入口合一(二)）的**反向补丁**（把「教务/管理员宫格不渲染 my/fees」那段删掉）；
  它与本地运行无关，而且**最多只能救回 5 项里的 1 项**（my/fees）。

**(2) 那 5 项为什么丢：L2 抓的是 admin 的 /my/apps**

~~~
$ python3 tests/smoke/zero_loss_reachability.py
L1：PASS 42 / FAIL 0 / BASELINE-404 1（共 43 条）        <- /my/time_off 卡在（请假卡没丢）
使用角色 admin 抓取 /my/apps（116803 bytes）              <- 关键：不是学生，是 admin
  MISS my/fees
  MISS my/checkins / my/journals / eval/my / eval/review
L2：出现 27 / 豁免 3 / 缺失 5（共 35 张）
L0：类契约失败 0   结论：有 5 项缺失（exit 1）
~~~

为什么会 fallback 到 admin：L2 先请 student 抓 /my/apps，而 H-1（commit 6b47565，
2026-09-18，学生门户首页合并）之后**学生/家长的 /my/apps 已 303 -> /my/home**，
脚本于是回退到 admin。admin 宫格里这 5 张卡**按角色合法隐藏**：

| 卡片 | 隐藏者 | 何时引入 | 性质 |
|---|---|---|---|
| my/fees | batch2.py 的 finance_hrefs（privileged_staff 过滤） | commit 78aa11d（**已提交**，2026-09-24 财务入口合一(二)） | 有意：侧栏已把教务/管理员送到后台账单管理 |
| my/checkins、my/journals、eval/my、eval/review | batch2.py 的 if not student: hidden \|= {...} | commit 2931c8a（**已提交**，成长组卡片按身份守卫） | 有意：非学生隐藏打卡/周记/评教入口 |

**(3) 决定性反证：这 5 张卡在"学生"视角一张不少**

以 stu@local（uid=8）实测：

~~~
/my/apps  303 -> /my/home（203 bytes 壳）     <- 学生的宫格已合并进 /my/home（H-1 设计）
/my/home  200（109320 bytes）：
    my/fees        True
    my/checkins    True
    my/journals    True
    eval/my        True
    eval/review    True
    my/time_off    True          <- 请假卡也在
~~~

=> 门禁报的「缺失」是**扫描目标**（/my/apps 对门户已是兼容层）与**扫描角色**（fallback 到 admin）
的组合产物，不是功能丢失。真正的修复方向属 H-1/门禁工作面（把 L2 改成对学生抓 /my/home），
**不在 S5 范围，本次未改**（改了就是替别人改门禁口径）。

---

## 7. 全部验收命令的 EXIT 与关键读数

| # | 命令 | EXIT | 关键读数 |
|---|---|---|---|
| 1 | python3 scripts/check_view_xpath.py --selftest | **0** | 断言 26 条全过；指纹 34e3fc67（r14） |
| 2 | python3 scripts/check_manifest_tracking.py | **0** | 13 模块 / 119 条引用；盘上缺失 0、未入库 0 |
| 3 | python3 scripts/check_qweb_dict_foreach.py --selftest | **0** | 断言 4 条全过（r2） |
| 4 | python3 tests/smoke/leave_split_approval.py --selftest | **0** | 16 PASS / 0 FAIL（尺子准） |
| 5 | python3 tests/smoke/leave_split_approval.py | **0** | **46 PASS / 0 FAIL**；A1–A14 全覆盖；leftover=0 |
| 6 | python3 tests/smoke/ux_v3_route_matrix.py | **0** | 检查点 495：PASS 495 / WARN 0 / PENDING 0 / FAIL 0 / ENV 0 |
| 7 | python3 tests/smoke/zero_loss_reachability.py | **1** | L1 42/0；**L2 缺失 5**（见 §6：非回归，已归因） |
| 8 | python3 scripts/check_english.py | **0** | must-fix 0 / brand 0 / **路由违规 0**（登记前 = exit 2 + 违规 1） |
| 9 | python3 scripts/check_odoo_trace.py | **1** | 命中 **1 处**：公开站 /alumni 200 的导航链接 /web/login?redirect=%2Falumni（去 Odoo 痕迹/品牌面，见下） |
| 10 | python3 scripts/check_accessibility.py | **0** | 违规 0（28/28 页扫全；与 BASELINE 0 一致） |
| 11 | bash scripts/safe_upgrade.sh edu_portal | **0** | 无失败特征；重启 web 后就绪 /web/login -> 302；日志 /tmp/edu19_upgrade.20260924-190850.log |
| 12 | python3 scripts/check_live_registry.py | **0** | 模型级 95/95 LIVE、**0 DARK**（字段级：匿名会话读不到 fields_get => 该项未验证） |

**第 9 条（check_odoo_trace）归因**：唯一命中是公开站 /alumni 页导航里的
/web/login?redirect=%2Falumni（登录入口）。处理该入口的正是
custom_addons/edu_brand/views/odoo_debrand.xml:102-130（注释逐字写着「网站页头『登录』
入口：portal.user_sign_in 硬编码 /web/login」）。edu_brand **不在我的改动范围**，
且 git status 显示该路径工作区与 HEAD 一致 => **与本功能无关、非 S5 引入**；
工具自己的口径也把它归在「基座品牌痕迹」面。

---

## 8. git add 的精确路径（未 commit）

~~~
git add tests/smoke/leave_split_approval.py   # 新建（A / 935 行）
git add tests/smoke/course_rep.py             # 修改（M / +82-16：夹具日期·时长·班主任 + 探活）
git add tests/smoke/F_roles_smoke.py          # 修改（M / +10-2：家长 sick 单 2 天 -> 1 天）
git add scripts/check_english.py              # 修改（M / +7：EXEMPT_ROUTES 登记家长身份 /my/time_off）
~~~

git status --short（这四条均已暂存）：

~~~
M  scripts/check_english.py
M  tests/smoke/F_roles_smoke.py
M  tests/smoke/course_rep.py
A  tests/smoke/leave_split_approval.py
 M tests/smoke/F_roles_smoke.md          <- 冒烟生成物，未 add
 M tests/smoke/course_rep_results.json   <- 冒烟生成物，未 add（本次之前就已是 M）
~~~

未改：生产（未 ssh / 未部署）、models/leave_flow.py、models/leave_transfer.py、
controllers/roles.py、controllers/batch1|2|3.py、controllers/enroll.py、views/*.xml、edu_brand/**。
**未 commit**（等队长 / S6）。

---

## 9. 结论

**S5 完成**：新建门禁 A1–A14 全绿（46 PASS / 0 FAIL）、两条既有冒烟归位
（course_rep 84/84 PASS；F_roles t9 PASS、t5 SKIP 与改前同口径）、check_english 回绿（exit 0）、
清场与 cron 43 验证闭环、全量 12 条验收命令逐条跑完，且**外部依赖项的红全部有独立归因**。

两条红均**不是本次引入**（证据见 §6 / §7）：

| 红 | 归因 | 归属 |
|---|---|---|
| zero_loss_reachability exit 1（L2 缺 5） | 门禁抓 admin 的 /my/apps；学生视角 5 张卡一张不少（/my/home 实测全在） | H-1 / 门禁工作面（**不是请假**） |
| check_odoo_trace exit 1（命中 1） | /alumni 页导航 /web/login（去 Odoo 痕迹面；edu_brand/views/odoo_debrand.xml 正是处理它） | 品牌 / 去 Odoo 痕迹工作面 |

**另有一条与本功能无关但需要有人认领的红**（F_roles 的 t12，不在 §7 清单内）：
t12 后台菜单探活 —— menu 576（在线课程）与 543（日常管理）action=NO_ACTION、active=f，
这是 2026-09-17 菜单收口的既定结果（code-map §4.1 明写「543 日常管理已停用」）；
请假自己的菜单 497「教务审批」-> res_model=edu.leave **有效=True**。t12 的期望清单需要
菜单收口的 owner 更新（本次未改，避免替别人改口径）。

### 9.1 需要队长裁决 / 知会的事项（按重要度）

1. **【产品口径，需队长确认】无班主任时"教师批不动"**：新判据 user == first_approver_id
   or privileged_staff() 之下，班级未设班主任 => 一级应批人 = 教务处组 ∪ 系统组，
   **普通教师（op_faculty）批不了任何请假单**。这与 course_rep 旧断言「老师/教务/管理员任一都能批」
   正面冲突。S5 的处置是**把夹具对齐新规则**（给夹具班填「班主任 = faculty@local」），
   **没有放宽任何断言**。若产品口径其实是「任何教师都能批本校请假」，那要改的是设计稿 §8.1，
   而不是夹具 —— 请队长明示。
2. **【队长授权的追加清理】374/375 已删**：reason 前缀确认是 S3-（转交行 reason 逐字写着
   「S3 冒烟：转交给教务」），按「除非你确认它也是你说的前缀」执行；审计 22 行一条未删，
   可逐字重建（§4）。
3. **【观察项】cron 43 的扫描不含归档单**（active_test=True 过滤 active=False），
   本库 leave 14 就因此不被提醒（§5.4）。
4. **【给 S6 的坑】Odoo shell 在 console() 之后无条件 cr.rollback()**
   （core cli/shell.py:148-149）—— 凡"写库"的 shell 片段必须显式 env.cr.commit()，
   否则夹具与清理会**静默回滚**（我在 A2/A4/A11/A14/cleanup 上踩过一次：
   单据"建了又没建"，读记录直接 MissingError）。
5. **【环境】本机 macOS 系统代理会被 requests 的 trust_env 采用**：裸 requests.get 到
   localhost 得 502，Session(trust_env=False) 才是 302。新写探活时请照 course_rep 的会话口径。
