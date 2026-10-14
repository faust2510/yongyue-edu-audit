# 评估任务生命周期搬进门户 —— 改动清单与原始证据

> 交付者：生命周期 agent（t-任务生命周期）｜ 2026-09-28
> 判据脚本：`python3 tests/smoke/assess_task_portal.py`（54 条断言，默认跑完**清夹具**；`--keep` 保留；`--purge` 只清）
> 结果落盘：`tests/smoke/assess_task_portal_results.json`

## 0 结论（一句话）

门户此前**没有**「评估任务」的新建/发布/排名单/结束，只能在 Odoo 后台做；而没人去后台
把它结束 ⇒ 本地库实测 3 个任务全部 open、closed = 0 ⇒ `/assess/my` 的「我收到的评估结果」
**一直是空的** ⇒ 学生看不到任何结果。本次把这条生命周期搬进门户，并端到端证明
"结束之后学生端真的从空变有"。

## 1 改动清单（文件 ⇒ 理由）

新增（都在可写范围内）：

1. `custom_addons/edu_assess/controllers/task_admin.py`（新文件，9 条路由）
   —— 新建/编辑任务、发布、结束、重新打开、名单生成/手工增删；**零新模型、零新字段**，
   状态机一律调模型自己的 `action_open/action_close/action_reopen/action_build_roster`。
2. `custom_addons/edu_assess/views/assess_task_admin.xml`（新文件，3 页）
   —— 沿用 `edu_portal.edu_page` 外壳 + 卡片 + `table-sm` + `?saved=1` 回执，不新造视觉。
3. `tests/smoke/assess_task_portal.py` + `tests/smoke/assess_task_portal_results.json`（新文件）
   —— 本报告的判据脚本与读数。

追加（一行/一段，未改他人内容）：

4. `custom_addons/edu_assess/__manifest__.py`：data 里加 `views/assess_task_admin.xml`
   （新视图必须在 manifest 里声明；文件名与引擎 agent 预置的那一行**逐字一致**）。
5. `custom_addons/edu_assess/controllers/__init__.py`：加 `from . import task_admin`。
6. `custom_addons/edu_assess/views/assess_portal.xml`：`edu_assess_home` 里追加
   admin 可见的「评估任务」入口块（挂在 `admin_tasks` 块之前，不动别人的卡片区与历程模板）；
   另按队长 B/C 项在 `edu_assess_my`、`edu_assess_results` 里加算分提示。
7. `tests/ui/surface.json`：登记 9 条新路由（2 页带三门口禁、2 条参数页按既有
   `assess_templates_detail` 的口径带 pending_gate + evidence、5 条写路由按 endpoint 口径）。

队长追加的 A–D 项（我持这些文件）：

8. `custom_addons/edu_assess/controllers/portal.py`
   - `_task_items()` 改为**只取启用叶子项**（走模型的 `task._leaf_items()`）—— 修 A 项：
     三层模板此前会把**分区行**也当成一列显示在门户矩阵里；
   - 新增 `_item_label()` / `_import_context()` / `_dup_column_hint()`，导出/空表/结果导出
     的列头改成「区名 / 项名」，导入侧先按标签精确匹配、再退到"名字唯一时的裸名"（兼容旧文件）；
     同名项用裸名导回会被**点名挡住**而不是随便挑一个 —— 修 D 项；
   - `assess_my` 接上 `EduAssessRoster._subject_domain()/_my_subject_rows()`，被评**教师**
     也能在 `/assess/my` 看到自己被评的结果；学生分支逐字未动 —— 修 B 项；
   - 模块 docstring 写入引擎硬约束：跨项/跨任务汇总禁止自己遍历 `score.value`，
     只读派生字段或走 `_item_cell/_group_subtotal/_breakdown` —— 队长 E 项。
9. `custom_addons/edu_assess/views/assess_portal.xml`（同上第 6 条里的 B/C 部分）

未改（刻意，避免与并发 agent 撞车）：`models/assess.py`、`security/**`、
`controllers/template_admin.py`、`views/assess_template_admin.xml`、
`views/assess_structure_views.xml`。

## 2 守卫（发布 / 结束 / 名单）与理由

发布 draft → open（四条硬拦，全部在写库前判）：

1. 只有草稿能发布（状态机不跳级）；
2. 模板必须启用 —— 否则学生侧 `/assess` 页自己会把它过滤掉，发布了也没人看得见；
3. 模板必须至少有一个可打分的叶子项 —— 没有列，矩阵是空的，是个死任务；
4. 发布时顺带建名单快照，**名单为空则整笔回滚**（savepoint + UserError）并报错。
   这条直接对着病根：名单空 ⇒ 收不到打分 ⇒ 结束后 `/assess/my` 还是空的。

结束 open → closed（三条"必须勾选确认"，不勾一律拒绝并**回显数字**；不硬拦）：

1. 还有名单行一行分都没收到 ⇒ 写出**具体人数**，说明结束后他们永远停在"未评"；
2. 匿名任务且有效答卷份数 < 匿名门槛 ⇒ 写出"结束后谁都不会看到明细"（样本不足）；
3. 模板设了"结果不对被评者公开" ⇒ 写出"结束后学生端不会出现这次结果"。

为什么不硬拦：一个班 30 人总有人不填，硬拦会把教务锁死在"永远结束不了"里 —— 那正是本次
要消灭的断链。放行但**知情**：未评人数/答卷份数写进 `edu_audit_log`，事后可查。

重新打开 closed → open：永远要确认（`/assess/my` 只展示已结束的任务 ⇒ 一重开这次结果立刻消失）。

名单增删：

- 任务已结束时**名单冻结**（生成/添加/删除三条写路由全部拒绝，提示先重新打开）；
- 删除一行**双钉**：既要在本任务下（`task_id`），又要那行自己的被评对象外键与派生键
  `subject_ref` 对得上 —— 只认 `subject_ref` 不够（它是普通 Char、RPC 可写）；
- **有打分记录的行拒删**（`score.roster_id` 是 ondelete='cascade'，删名单会静默连带删掉打分），
  口径与评分项"有分拒删"一致。

改任务：已有名单或已有打分**不许换模板**（否则旧打分对不上新评分项，结果静默错位；
模型层没有这条约束，故落在页面守卫，已在报告点名）。

## 3 三类证据（原始输出）

### 3.1 正向：一个任务从门户走完 草稿 → 发布 → 名单 → 结束，状态真的落库

（`python3 tests/smoke/assess_task_portal.py` 的 B/C 段，SQL 前后对照）

```
PASS #B1.1 门户建任务 → 303 回任务页且库里出现 draft 行
     HTTP 303 Location=/assess/tasks/231?saved=1 ｜ 库内行数 0→1 ｜ state=draft
PASS #B1.2 多选的"参与班级"真的写进了 m2m 关系表（不是只取第一个）
     关系行数=1（期望 1）—— 路由 **post 拿不到多选，必须走 form.getlist
PASS #B2.1 门户发布 → 303 且 state 落库为 open、名单快照从 0 到 N
     HTTP 303 ｜ state=open ｜ 名单行数 0→1
PASS #B3.1 名单手工添加一行 → 303 且库内 +1            HTTP 303 ｜ 行数 1→2 ｜ roster_id=…
PASS #B3.2 名单逐条移除 → 303 且库内回到原值            HTTP 303 ｜ 行数 2→1
PASS #B4.1 教师走既有门户路由打分 → 303 且打分落库、名单行转"已评"
     HTTP 303 ｜ 打分条数=3 ｜ 该行 state=done ｜ csrf 来源 /assess/grade/231（HTTP 200）
PASS #B5.1 门户结束 → 303 且 state 落库为 closed        HTTP 303 ｜ state=closed
PASS #B6.1 发布与结束都留下审计（含未评行数）
     审计条数=2 ｜ 结束详情=…名单 2 行（未评 1 行）、答卷 1 份；结束前已确认 1 条风险提示。
```

### 3.2 闭环：结束后学生端 `/assess/my` 从空变有（本任务要修的症状）

（同一脚本 C 段；前后两次页面读数 + 数值与 SQL 对齐 + 因果对照）

```
INFO #A2 学生端 /assess/my 的"我收到的评估结果"读数（夹具建之前）
     HTTP 200 ｜ 空态文案"暂无已结束的评估结果"在页面上=True ｜ 页面长度=36040
PASS #C1.1 结束前：学生端 /assess/my 不含本次任务          HTTP 200 ｜ 页面出现本次任务=False
PASS #C1.2 结束后：学生端 /assess/my 出现本次任务的结果卡
     HTTP 200 ｜ 含本次任务=True ｜ 读数：→ 教师评学生（验收） · 【冒烟】门户生命周期验收
     评分项 得分 课堂参与 20 作业完成 …
PASS #C2.1 页面上的分数 == SQL 里该行的打分值
     SQL=['20.00','30.00','10.00'] ｜ 页面读出=['20','30','10']
PASS #C3.1 因果对照：重开后学生端又变空、再次结束后又出现（"结束"就是那一步）
     重开 HTTP 303 → 含任务=False ｜ 再结束 HTTP 303 → 含任务=True ｜ state=closed
```

### 3.3 反向：注入故障后断言**变红**，还原后逐字恢复

注入①（跳过结束守卫：`if warnings and not confirm` → `if False and …`），升级后跑 D 段：

```
EXIT=1
FAIL #D1.1 有未评行时不带确认结束 → 被拒（303 带 error）且 state 不变
      HTTP 303 Location=/assess/tasks/224?saved=1 ｜ state=closed     ← 没被挡住，真的关掉了
FAIL #D3.1 进行中的任务不能再"重新打开"（状态机不跳级）
      HTTP 303 Location=/assess/tasks/224?saved=1 ｜ state=open
== 汇总 == 断言 22 条：PASS 20 / FAIL 2
```

还原①（文件逐字还原 + 升级）后同样跑 D 段：

```
EXIT=0  == 汇总 == 断言 22 条：PASS 22 / FAIL 0   全绿。
```

注入②（权限判据失效：`_is_allowed()` 直接 `return True`），升级后跑 E 段：

```
EXIT=1
FAIL #E1.1 4 条页面路由 × 学生/教师/家长 = 12 探 → 全部 303 /my/home
      异常：['学生 /assess/tasks → 200', '教师 /assess/tasks → 200', …]
FAIL #E2.1 5 条写路由 × 学生/教师/家长 = 15 探（带合法 csrf）→ 全部 303 /my/home
      异常：['学生 POST /assess/tasks/save → 303 /assess/tasks/227?saved=1', …]   ← 越权建出了任务
FAIL #E3.1 越权写入残留 0：探完逐项快照相等
      前后差异：{'tasks': (4, 7), 'audit': (1955, 1958)}
== 汇总 == 断言 19 条：PASS 16 / FAIL 3
```

最终还原后：

```
EXIT=0  == 汇总 == 断言 19 条：PASS 19 / FAIL 0   全绿。
还原校验：文件逐字还原（byte-for-byte 比对）
```

### 3.4 越权（3 身份 × 全部 9 条新路由，带各自会话的合法 csrf）

```
INFO #E0 越权探之前的 SQL 快照  {"tasks": 4, "rosters": 12, "scores": 11,
        "state": "closed", "task_roster": 2, "audit": 1915}
PASS #E1.1 4 条页面路由 × 学生/教师/家长 = 12 探 → 全部 303 /my/home      异常：无
PASS #E2.1 5 条写路由 × 学生/教师/家长 = 15 探（带合法 csrf）→ 全部 303 /my/home   异常：无
PASS #E3.1 越权写入残留 0：探完逐项快照相等（任务/名单/打分/状态/审计）   前后差异：无（逐项相等）
PASS #E4.1 未登录访问 → 走 auth='user' 兜底（303 到登录页）
      HTTP 303 Location=/web/login?redirect=%2Fassess%2Ftasks%3F
```

### 3.5 控制组（断言不是恒真/恒假）

```
PASS #F1.1 系统组（admin，同为授权层）访问同一批页面 → 200       读数 4 条全 200
PASS #F2.1 学生/教师访问自己该看的页 → 200                      学生 /assess/my=200 ｜ 教师 /assess/grade/=200
PASS #F3.1 不存在的任务 id → 303 带错误                          HTTP 303 Location=/assess/tasks?error=任务不存在…
PASS #H1.2 对照：矩阵修前口径（含分组）会是 11 列 —— 读数确实变了   现在评分列 8 ｜ 含分组会是 11
PASS #H6.1 控制组：扁平模板（列头=项名，无前缀）仍可往返且零变更
```

## 4 队长追加的 A–D 项：证据

### A 门户矩阵只列叶子（三层模板）

```
INFO #H0 夹具：3 区 8 叶子（跨区同名：窗户有灰尘/污渍 ×3、垃圾未倒 ×2），全部扣分制
PASS #H1.1 门户矩阵列数 == 叶子项数（8），不含任何分组名
     行标签=['学生'] ｜ 评分列 8 列=['窗户有灰尘/污渍','窗户有灰尘/污渍','窗户有灰尘/污渍',
     '墙面有污渍','垃圾未倒','垃圾未倒','灶台油渍','床铺不整'] ｜ 分组名混入=无
```

### B 被评教师在 /assess/my 看到自己的结果 + 反向隔离 + 开关有牙

```
INFO #G0 夹具 模板=… ｜ 任务A=…（教师 17）｜ 任务B=…（教师 43）
PASS #G1.1 被评教师打开 /assess/my → 200 且看到自己被评的分数  HTTP 200 ｜ 读到格子=['15','25']
PASS #G2.1 反向：教师 A 拿不到教师 B 的评教结果（任务 B 名不在页面上，卡片只有 1 张）
PASS #G2.2 控制组：任务 B 的数据确实在库里、教务看得到（A 看不到不是"数据没有"）
PASS #G4.1 闸门：模板 score_visible=False ⇒ 教师端只看到"不公开"的说明、看不到分数
PASS #G5.1 控制组：开关打开后同一读数立刻回来
```

### C 缺一路 / 未评项 / 可评满分的前台消费者

`/assess/my` 结果卡与结果页都新增了消费者：缺一路时给出**警告条**并明确"不计入总分
（不按一路折算、也不按 0 算）"；算分不完整时**不显示总分**（避免读成一个偏低的分）；
有未评项时给出清单与"当前可评满分 X 分（未评项不参与归一）"。读数由
`missing_tracks / complete / missing_items / reachable_max / weighted_total / grade`
派生字段提供（不自己求和）。

### D xlsx 区名往返（同一模板内同名检查项）

```
PASS #H2.1 导出结果：列头 = 学号/姓名 + 区名 / 项名 标签（8 列），同名项可分
     表头=['学号','姓名','厨房 / 窗户有灰尘/污渍','卫生间 / 窗户有灰尘/污渍',
     '卧室 / 窗户有灰尘/污渍','厨房 / 墙面有污渍','卫生间 / 垃圾未倒','卧室 / 垃圾未倒',
     '厨房 / 灶台油渍','卧室 / 床铺不整','加权总分','平均分']
PASS #H3.1 同一文件导回：预览可写入 2 行 / 待修正 0 行，且没有"未知列头"
PASS #H3.2 反向：裸项名列头导回 → 被"同名项"提示挡住（区名前缀确有必要）
PASS #H4.1 原样导回后逐格零变更（幂等：导出→导回 = 不动数据）
     HTTP 303 ｜ 格子 16 个 ｜ 前后相同=True
PASS #H5.1 导出空表：同一套区名标签列，且没有分组列
PASS #H6.1 控制组：扁平模板（列头=项名，无前缀）仍可往返且零变更
```

### E 引擎口径（写进 docstring 的硬约束）

`controllers/portal.py` 模块 docstring 新增一节：双轨合并/扣分制只有一个入口
`EduAssessRoster._item_cell`（以及 `_group_subtotal` / `_breakdown`）；跨项/跨任务汇总
**禁止**自己遍历 `edu.assess.score.value`（扣分制下它存的是"扣了多少"）。

## 5 回归与门禁（全绿读数）

```
python3 tests/smoke/eval_rebuild.py          → exit 0 ｜ 58/58 PASS
python3 tests/smoke/assess_engine_v2.py      → exit 0 ｜ 74/74 通过
python3 tests/smoke/assess_history.py        → exit 0 ｜ 32/32 通过（学生视角未被改坏）
python3 tests/smoke/ux_v3_route_matrix.py    → exit 0 ｜ 检查点 520：PASS 520 / WARN 0 / FAIL 0
python3 scripts/check_accessibility.py       → exit 0 ｜ 违规 0 条（critical/serious/moderate/minor 全 0）｜ 53/53 页
python3 scripts/check_english.py             → exit 0 ｜ must-fix 0 / brand 0 / 路由违规 0 / 夹具残留 0
python3 scripts/check_ui_surface.py          → exit 0 ｜ 违规 0 条（登记 296 条）
python3 scripts/check_live_registry.py       → exit 0 ｜ 95/95 模型 LIVE、0 DARK
python3 scripts/check_view_xpath.py          → exit 0 ｜ 失败项 0
python3 scripts/check_qweb_dict_foreach.py   → exit 0 ｜ 失败项 0
python3 scripts/check_manifest_tracking.py   → exit 0 ｜ 盘上未入库 0
python3 tests/smoke/assess_task_portal.py    → exit 0 ｜ 54/54 PASS（夹具默认清干净）
```

## 6 我没做成 / 不确定的部分（诚实清单）

1. **矩阵列头仍是裸项名**（`窗户有灰尘/污渍` 会出现三次）。A 项只要求"只列叶子、不含分组名"，
   本仓既有断言（`eval_rebuild` V1-④/V2b-②）也按裸名匹配表头 ⇒ 我没改矩阵表头口径。
   三层模板下这几列人眼可分不出是哪个区，**建议下一步**再给矩阵加一级分组表头（xlsx 侧已经做了）。
2. **`/assess/my` 的教师分支与课程/班级无关**：教师被评的行 `batch_id` 为空，靠
   `faculty_id.user_id / partner.user_ids` 两条链收敛（模型口径）。若某位教师的账号既不是
   `user_id` 也不在 `partner.user_ids` 里，他看不到自己被评结果 —— 这类账号反查属于
   `edu_schedule/models/identity.py` 的口径范围，我没有改（避免与 identity 统一化那条线撞车）。
3. **`/assess/my/history` 仍然只认学生**：`assess_history.py` 的 H5f 明确要求"教师请求学生本人的
   历程 → 弹回门户"，所以我没有把教师被评时间线接进去。教师要看历次评教，目前只有结果页。
4. **名单"移除"对有打分的行是硬拒**（不是"停用"）。设计 §5.7 提到的 roster 级"停用位"不在
   12 字段清单里，模型层也没有，所以按模型既有护栏口径处理；若产品上需要"停用名单行"，
   得先加字段（我没有加）。
5. **换模板护栏在控制器层**，模型层没有这条约束：后台直接改 `template_id` 仍可绕过
   （引擎 agent 的 `models/assess.py` 我不能改）。建议在模型层补一条 `@api.constrains`。
6. **注入实验窗口**：两次注入各占一次 `safe_upgrade`（约 1 分钟），期间共享工作区的其他
   agent 若正好跑门禁可能读到"学生能进 /assess/tasks"的中间态；我已把窗口压到最短并逐字还原
   （文件 byte-for-byte 比对）。若别人曾在那两个窗口内取数，请重跑。
7. **`--only` 段可单独跑**：`--only d`/`--only e` 是注入实验用的入口，不是常规用法。
8. 我没有动生产、没有 commit；新增文件已 `git add`，其余改动留在工作区由队长统一提交。
