# 实施代理 Z · B6 结果下钻（exec_Z）

日期：2026-08-23　范围铁律：仅动 `edu_quiz/controllers/portal.py`、`edu_quiz/views/edu_quiz_portal_views.xml`、`edu_portal/controllers/batch3.py` 的 users_result_overview 函数体。未执行 docker/odoo/curl。

## 缺口回顾
B6：原站 `/users/result-overview` 每条成绩卡有「View Result」按钮 → `/exam/result/<id>` 单次详情；本地行内无任何入口。本任务复用本地已有结果页 `/quiz/<qid>/result/<aid>` 作为下钻目标（不新增路由）。

## 改动清单

### 1. custom_addons/edu_quiz/controllers/portal.py
- `quiz_list`（L27-L40）：attempts 循环里加 `latest` 字典（search 沿用模型 `_order=create_date desc`，`setdefault` 即每测验最近一次 attempt 的 id）；items 行补 `'best_attempt_id': latest.get(q.id)`。归属校验沿用现有写法 `[('student_id', '=', student.id)] if student else []`。
- `quiz_result`（L99-L107）：**补归属校验**（原先只查存在性，任何登录用户可看任意 attempt）。现在要求 `attempt.student_id.id == student.id`（op.student.user_id=当前用户）且 `attempt.quiz_id.id == qid`，否则 303 回 `/quiz`。这是 B6 入口增多后的安全前提，也是「所有链接目标真实可达+归属」的验收项。

### 2. custom_addons/edu_quiz/views/edu_quiz_portal_views.xml（列表卡 L31-L53）
- 「最好 x%」徽章从外层 `<a>`（指向 take 页）内部移出，改为卡片 div 的**兄弟节点** `<a t-if="it['tried']" t-att-href="'/quiz/'+quiz.id+'/result/'+best_attempt_id">`。
- 原因：徽章原在整卡 `<a>` 内部，HTML 不允许嵌套锚点（浏览器会把外层锚点截断、绝对定位失效破版）。改为兄弟节点后卡片主点击仍=开始作答，右上角徽章=结果页链接。
- 卡片 div 加 `position-relative`；徽章加内联 `position:absolute;top:12px;right:12px;text-decoration:none` 保持原位。样式说明：`.oe_count` 的紫色背景选择器是 `> a .oe_count`（后代），移出后不再命中，徽章将显示模板本就写好的 `text-bg-success`(≥60)/`text-bg-secondary`(<60) 配色——这正是原代码条件表达式的意图；如需维持全站紫色，后续可在 CSS 里给 `.o_portal_index_card > a.oe_count` 补一条规则（未动，超出本代理权限）。
- 无 attempt（tried=False）时不渲染该 `<a>`，保持原样。

### 3. custom_addons/edu_portal/controllers/batch3.py（仅 L758-L777 函数体内）
- `users_result_overview` 在 `items = self._result_items(student)` 之后为每行补 `attempt_url`：
  - 取本人 attempts：`('student_id', '=', student.id)`（归属校验），并守卫 `'edu.quiz.attempt' in request.env`（edu_portal 未依赖 edu_quiz，模块未装时优雅降级为无链接）。
  - 行(exam)与 quiz 无外键：先按 **exam 名 == quiz 名精确匹配**（同名取最近一次）；匹配不到回退到**本人最近一次 attempt**（`attempts[:1]`）。这样凡确有 attempt 的学生每行都有可达且属于本人的下钻目标；完全无 attempt 时 `attempt_url=''`，模板不渲染链接。
- 未动 `_result_items`、`omr_exam_result` 及文件其它部分（OMR 页不受影响）。

## ⚠ 需主代理代改的 batch3.xml 精确补丁（本代理禁止编辑该文件）
文件：`custom_addons/edu_portal/views/batch3.xml`，模板 `edu_result_overview` 成绩表末列（当前行号 958-960；若其它代理已改动请按内容匹配）：

old（精确）：
```xml
                                    <td>
                                        <span t-att-class="'badge ' + (it['status'] == '及格' and 'bg-success' or 'bg-danger')" t-out="it['status']"/>
                                    </td>
```
new（精确）：
```xml
                                    <td>
                                        <span t-att-class="'badge ' + (it['status'] == '及格' and 'bg-success' or 'bg-danger')" t-out="it['status']"/>
                                        <a t-if="it['attempt_url']" t-att-href="it['attempt_url']" class="ms-2 small text-decoration-none">查看详情 <i class="fa fa-arrow-right" aria-hidden="true"/></a>
                                    </td>
```
说明：对齐原站「View Result →」位置（行尾状态徽章旁）；控制器保证每行必有 `attempt_url` 键（无 attempt 时为空串，t-if 不渲染）。套用后需升级 `-u edu_portal` 生效。

## 自查
- [x] 路由复用现有 `/quiz/<qid>/result/<aid>`，零新增路由。
- [x] 归属校验：/quiz 列表沿用 `student_id=当前生`；结果页新增本人+quiz 一致性双校验；batch3 行链接只取本人 attempt。
- [x] py_compile 两份 .py 通过；XML minidom 解析通过（PY_OK/XML_OK）。
- [x] 未执行 docker / odoo / curl，未改清单外任何文件（含 batch3.xml、CSS、manifest）。
- [x] 嵌套锚点规避：徽章为卡片 `<a>` 的兄弟节点。

## 主代理回归建议（需运行环境，本代理未执行）
1. 演示学生登录 → `/users/result-overview` 有成绩行且有测验 attempt 时，行尾出现「查看详情 →」，点击落在 `/quiz/<qid>/result/<aid>` 200。
2. 同学生 `/quiz` 列表：已尝试卡片右上「最好 x%」为链接，点击=最近一次结果页；未尝试卡片无链接。
3. 换另一账号直接 GET 他人的 `/quiz/<qid>/result/<aid>` → 应 303 回 `/quiz`（验证新归属校验）。
4. 无任何 attempt 的新学生：两处均保持原样无链接。
