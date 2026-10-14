# 符号级死代码扫描（2026-10-02 立）

> 目的：本目标含「去冗余代码」。T1 已把**路由级 / 资源级**的死代码扫到底（309 路由 0 可删、
> 资源 30/30 有引用），但**函数级**从未扫过。本文是那一次扫描的口径、结果与逐条定性。

## 1. 口径（可复算）

找「在 `custom_addons/` 里定义了、但**全仓再没出现过第二次**的函数名」。
刻意保守，避免误报：

· 只报**全仓出现次数 ≤ 1**（即只有定义处）的名字；统计范围含 `.py/.xml/.js/.md/.csv/.po`；
· 排除 dunder；
· **排除 `@http.route` 装饰的处理器** —— 它们由 URL 引用，不是死代码。
  ⚠ 这条排除**必须**能识别**多行**装饰器：第一版只往上找「以 `@` 开头的行」，
  而 `@http.route(...)` 换行书写时紧邻 `def` 的是**续行**（不以 `@` 开头），
  于是 307 个处理器全被当成候选 ⇒ 候选从 130 条假降到 **15 条真**。
  ⇒ 教训：**过滤器的识别率决定了整个扫描的信噪比**，过滤条件本身要先量一遍。

数字：993 个函数定义 → 排除 307 个路由处理器 + 框架约定前缀 → **15 个候选**。

## 2. 逐条定性（15 条）

| # | 符号 | 位置 | 定性 | 依据 |
|---|---|---|---|---|
| 1 | `my_time_off_export` | edu_portal/controllers/batch3.py | ✅ **已修（真缺陷）** | 实现完整却丢了 `@http.route` ⇒ 从未注册；`views/batch3.xml:638` 的「导出 CSV」指着它 ⇒ 实测 **404**。已补装饰器，实测 **404 → 200（text/csv，1661 字节）**。 |
| 2 | `_scale_violation` | edu_assess/models/assess.py:337 | ⚠ **未接线的设置** | `scale_rule` 字段存在且**视图里可改**（assess_structure_views.xml:43），但唯一消费者就是它自己，且**全仓无人调用**；打分保存路径（`assess_grade_save`/`assess_fill_save`）里**没有**任何校验调用 ⇒ **管理员设了「10 的倍数」也不会被拦**。 |
| 3 | `_track_scorer_kind` | edu_assess/models/assess.py:956 | ⚠ **未接线的设置** | `objective_scorer_kind`/`subjective_scorer_kind` 两个字段可编辑（task_admin.xml:274「主观路打分人」），但消费它们的 `_track_scorer_kind` **无人调用**；实际打分人判定走的是**任务级** `scorer_kind`（portal.py:436/508/576/605）⇒ **双轨各自的打分人下拉设了没用**。 |
| 4 | `_copy_conflicted` | edu_schedule/controllers/main.py:310 | 重构残留（建议删） | 同文件 `_slot_conflict_dims` 的注释写明它是「本模块**唯一**的重叠判定实现：旧 `_slot_conflicted` 现在是…」⇒ 本条是被取代后的遗留。 |
| 5 | `_ordered_items` | edu_assess/models/assess.py:304 | 重构残留（建议删） | docstring 说「渲染小计/表头都用这个顺序」，但实际渲染顺序在别处**内联**实现（assess.py:426/475/1363/1377/1411 各有 sorted）⇒ 说明文字已过时。 |
| 6 | `_percent_summary` | edu_assess/models/assess.py:400 | 重构残留（建议删） | docstring 自称「给界面/测试用」，两处都无人用。 |
| 7 | `_weight_rollup` | edu_assess/models/assess.py:408 | 待定 | 派生权重合计；无引用，但注释指向设计文档 §4 #8，删前应确认不是留给模板的。 |
| 8 | `_course_cards` | edu_portal/controllers/batch2.py:1021 | 重构残留（建议删） | 模板 `study.xml:360-374` 用的是变量 `course_cards`/`quick_cards`（无下划线），由别处构造 ⇒ 这两个 helper 是被取代的旧实现。 |
| 9 | `_quick_cards` | edu_portal/controllers/batch2.py:1044 | 同上 | 同上。 |
| 10 | `_reminder_minutes` | edu_schedule/models/session_ext.py:197 | 疑似残留 | 提醒链路（cron → `_notify_upcoming` → `_reminder_body`/`_reminder_users`）走通，但提前量参数是在别处直接读的。 |
| 11 | `lock_state_map` | edu_portal/models/lms.py:96 | 疑似残留 | docstring 称「列表页用」，但 lms.py 里再无 `lock_state` 相关引用。 |
| 12 | `conflict_kind_label` | edu_schedule/models/session_ext.py:102 | 待定 | 注释自称「模板/弹窗可选使用」—— 属**预留 API**，删前需产品确认。 |
| 13 | `is_delegate_of` | edu_portal/models/leave.py:237 | 待定（**公开名，RPC 可达**） | `edu.approval.delegate` 模型的公开方法；Odoo 对**非下划线开头**的方法**允许 RPC 调用**，故「仓内无引用」不足以判死。 |
| 14 | `delegators_of` | edu_portal/models/leave.py:247 | 同上 | 同上。 |
| 15 | `user_of_profile` | edu_schedule/models/identity.py:172 | 待定（**公开名**） | identity 是「唯一口径」模块，`users_of_profile` 被广泛使用（如 session_ext.py:288），本函数是它的单数包装，可能是**刻意留的对外口径**。 |

## 2.1 第二轮：已删除（2026-10-02 晚，commit 见下）

删除前逐条复核：**全仓（含 `openeducat_erp` 基座、docs、tests、全部文件类型）**引用计数，
确认除「定义处 + 本台账自身」外**再无引用**；再按名字成块删除（不是手删，避免留错缩进/空行），
每删一处立刻 `ast.parse` 复核语法。**共删 78 行 / 6 个函数**：

| 符号 | 位置 | 删除行数 |
|---|---|---|
| `_copy_conflicted` | edu_schedule/controllers/main.py | 18 |
| `_ordered_items` | edu_assess/models/assess.py | 16 |
| `_percent_summary` | edu_assess/models/assess.py | 7 |
| `_course_cards` | edu_portal/controllers/batch2.py | 21 |
| `_quick_cards` | edu_portal/controllers/batch2.py | 13 |
| `_reminder_minutes` | edu_schedule/models/session_ext.py | 3 |

**删除后验证**：`-u edu_schedule,edu_assess,edu_portal` EXIT=0；受影响页面逐个实测 ——
`/my/home` 200（115KB）、`/my/study` 200、`/assess/tasks` 200、`/timetable/bulk` 200；
四轴 UI 门禁 **A0/B0/C0/D0，样本有效=True**。

`_reminder_minutes` 的定性特别记录：它读的是 `edu.meeting.reminder_minutes` 参数，
而 `cron_session_reminder` 在**自己函数体内第 359 行**直接读了同一个参数 ⇒
**行为是在线的，删掉的只是一份重复实现**（不是「删掉功能」）。

## 2.2 第二轮新发现：**模板里也有死代码**（未接线，只登记不删）

删 `_course_cards` / `_quick_cards` 时顺带查出它们**为什么会成为孤儿**：

`edu_portal/views/study.xml:360-374` 有两段以变量 `course_cards` / `quick_cards` 为条件的区块 ——
**但全仓（`.py`/`.js`/`.xml` 的 `t-set`）没有任何地方给这两个变量赋值**。
⇒ `t-if="course_cards"` 恒假 ⇒ **这两段区块从来没有渲染过**（实测：`ux3-row` / `ux3-quick-item`
在 `/my/home` 与 `/my/study` 的 HTML 里出现 **0 次**）。

三件东西只差最后一根线：helper（`_course_cards`/`_quick_cards`，从未被调用）→ 模板区块（等变量）→
控制器（从不传变量）。三者各自存在，**从未连起来**。归档日志（`.agent-teams/archive/…`）显示
它们本是「首页瘦身手段之一/之二」，而 `/my/home` 后来改成了 Timeline 工作台 ⇒
**是改版换掉的那一版遗留**，不是还没做完的新功能。

**处置：只登记，不删也不接线。** 不接线 —— 往已经定型的 Timeline 首页里塞回两段卡片是**版面决策**；
不删 —— 万一产品要把「我的课程」卡片做回来，这是现成的实现。两类都写在这里，交产品裁定。

## 3. 本轮采取的行动（以及**故意没做**的）

**做了**：#1 修掉（真实用户可见缺陷，生产同样存在），并立起 `scripts/check_inpage_links.py`
（页内链接门禁，红→绿自证见该脚本注释与 commit 1d32ae5）。

**没做**：#2/#3 是**未接线的设置**，接线会**改变行为** ——
刻度校验一旦接上，会让原本能填的数字被拒；双轨打分人一旦接上，会改变谁能给谁打分。
两者都是**产品口径问题**，不是「顺手补一行」的活，故**只登记不动手**。

**也没做**：#4–#15 的删除。理由：其中**公开名方法（#13/#14/#15）RPC 可达**，
「仓内无引用」**不足以判死**；而 #7/#12 的注释指向设计文档或自称预留 API。
删除应当**单独一次改动**、逐条复核，而不是跟在一次 bug 修复后面顺手扫掉 ——
（上一轮我自己就因为「顺手改一个观感问题」引入了 118px 横向溢出，是门禁兜住的。）

## 4. 复算方法

扫描脚本是一次性的（存于 /tmp，未入库）。要复算：
① 统计每个 `def` 名字在全仓的出现次数；② 排除 `@http.route` 处理器（**注意多行装饰器**）；
③ 取 count ≤ 1 者；④ **逐条人工定性** —— 机器只能给候选，定不了性。
第 ④ 步是本文件存在的理由。