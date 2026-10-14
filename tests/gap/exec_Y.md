# 实施代理 Y（门户核心组）执行报告

工作目录：`custom_addons/edu_portal/`
本次改动文件（全部在允许清单内，未执行 docker/odoo/curl）：

- `controllers/batch2.py`
- `views/batch2.xml`
- `models/alert_read.py`
- `static/src/js/alerts_read.js`（新增）
- `__manifest__.py`

---

## 任务1 · B1 学业进展页 `/student/progression`

**改动**：batch2.py 新增 `student_progression()`（grade-book 之后、图书馆之前）；views/batch2.xml 新增模板 `edu_progression`。

**要点**：
- 归属校验：`current_student()` 取当前登录用户的学生档案，无档案时页面顶部 alert-warning 提示。
- 各科出勤率：`op.attendance.line` 按 present / late / absent / excused 统计；科目取
  `attendance_id.session_id.subject_id`，无 session/科目时回退课程名「未分科目」兜底；
  出勤率 =（present+late)/总数，每科一行 bootstrap progress 进度条（≥75 绿 / ≥50 黄 / 其余红）。
- 作业提交率：`op.assignment`（按学生 batch）总数 vs `op.assignment.sub.line` state in submit/accept。
- 近期测验均分：`edu.quiz.attempt`（submitted）按 score/total 折算平均百分比；模块未安装时 try/except 静默跳过。
- 请假次数：`edu.leave` 计数（safe_count）。
- 页面结构：顶部 oe-statrow 四统计格（总出勤率/作业提交/测验均分/请假次数）+ 各科进度条卡 +
  作业/测验分段卡；无任何数据时走 `oe-empty` 空态。

## 任务2 · B4 布告栏 Circular tab

**改动**：batch2.py `notice_board()` 重构；views/batch2.xml `edu_notice` 更新；models/alert_read.py 内 `_inherit = 'edu.notice'` 补 `category` 字段。

**要点**：
- notice.py 不在允许编辑清单内，故在 models/alert_read.py 以 `_inherit` 轻量扩展
  `category = Selection([('notice','通知'),('circular','Circular')], default='notice', index=True)`；
  模块升级时 ORM 用默认值回填既有记录，无需数据迁移 XML（符合"xml data 不必迁移旧数据"）。
- 控制器：`box=circular` → domain 加 `('category','=','circular')`；其余取值（含默认）一律
  `category='notice'`。搜索/排序在类别过滤后生效；旧快捷过滤 active/this_month/high 保留，
  在当前 tab 数据集上收窄（旧链接会落回通知 tab）。统计条数字改为按当前类别统计。
- 模板：顶部两个切换 tab 链接 `?box=notice`（默认高亮）/ `?box=circular`，active/ghost 样式随 box 切换；
  排序下拉与搜索表单会携带 box 参数保持在当前 tab；空态文案区分通知/Circular。

## 任务3 · B9 成绩簿下载

**改动**：batch2.py 新增 `GET /grade-book/report/download`；views/batch2.xml `edu_gradebook` 头部加按钮。

**要点**：
- 归属校验：非学生用户 redirect 回 `/grade-book`（该页自身有无档提示）。
- CSV 列：科目 / 考试 / 得分 / 满分，数据源与列表页一致（`op.marksheet.line` → result_line，
  按 student_id 过滤，sudo 只读），顺序 generated_date desc。
- 编码：`\ufeff` BOM 头（utf-8-sig）防 Excel 中文乱码；`request.make_response` 返回，
  Content-Type `text/csv; charset=utf-8`，Content-Disposition attachment，文件名
  `gradebook_report_YYYYMMDD.csv`。
- 列表页头部右侧新增「下载报告」按钮（oe-gb-head 改 d-flex，仅 has_records 时显示）。

## 任务4 · D5 解隐

**改动**：batch2.py `_DEFAULT_HIDDEN_CARDS`。

**要点**：
- 移除隐藏：`my/orders`、`my/payment_method`、`my/dms`、`my/asset-request`、
  `openeducat-omr/student/exam`、`openeducat-omr/exam-result`（本地路由可用）。
- 保留隐藏：`my/rfq`、`my/purchase`、`student/newregistration/info`（路由缺失）。
- 注意：系统参数 `edu.portal_hidden_cards` 一旦设置会整体覆盖默认值；主代理联调时若 DB 里
  存在该参数需清掉才能看到解隐效果（代码路径 `_hidden_cards()` 未改语义）。

## 任务5 · D3 分类已读语义

**改动**：models/alert_read.py、batch2.py（`_alert_counts`/`_alert_seen_map`/`_home_categories`/`edu_home`/新路由）、views/batch2.xml（提醒区）、static/src/js/alerts_read.js（新增）、__manifest__.py。

**要点**：
- 模型：`edu.alert.read` 新增 `seen_map = fields.Json(default=dict)`（{key: 已读水位}），
  保留 `last_total` 兼容旧字段；新增方法 `_raise_watermarks(counts)` 只升不降。
- 计数：`_home_categories` 提醒区每类未读 = `max(0, 当前计数 - seen_map.get(key,0))`，
  折叠头徽标与首页铃铛 `bell` = 各类未读之和（不再用 total−last_total 差值）。
- key 对齐：`_ALERT_CARDS` 的 href 即 key，控制器 `_alert_counts()` 与模板卡片
  `data-alert-key` 同源生成，天然对齐；'student/profile'（Placement 无数据源）不计入。
- 路由：batch2.py 新增 `EduAlertReadV2(EduParentPortal)` 覆盖 `POST /alerts/mark_read`
  （叶子类路由机制，同 EduPortalHomeV2 覆盖 /my/home 的既有模式；roles.py 未改动）。
  带 key 且合法 → 仅把该类水位提到当前值；不带 key → 全部提满，兼容现有「全部标为已读」表单。
- 前端：alerts_read.js（`/** @odoo-module **/` 头）监听 `.portal_alert_category` 内
  `a[data-alert-key]` 点击，fetch POST（FormData：csrf_token + key，keepalive:true），
  不 await 不阻塞导航；csrf 优先取 `meta[name=csrf_token]`，并在提醒区内置
  `input.oe-alert-csrftoken` 作兜底（meta 缺失也能上报）。徽标 unread=0 时不渲染。
- __manifest__：web.assets_frontend 注册 alerts_read.js。

---

## 验收自查

| 检查项 | 结果 |
| --- | --- |
| Python 语法（py_compile/AST） | ✅ 通过 |
| XML well-formed（ElementTree 全量解析） | ✅ 通过 |
| JS 语法（node --check） | ✅ 通过 |
| 模板 id 与 render() 同文件对应 | ✅ edu_progression / edu_notice / edu_gradebook 均在 views/batch2.xml |
| 归属校验 | ✅ progression/download 均 current_student()+student_id 过滤；notice 为公共公告无需归属 |
| 空态 | ✅ progression(oe-empty)、notice(区分文案)、download(空数据仍出表头 CSV) |
| QWeb 已知坑 | ✅ 属性内无 <t> 标签；动态属性全用 t-attf/t-att；URL 拼接 & 已转义 &amp; |
| 未执行 docker/odoo/curl | ✅ 仅静态检查 |
| 文件白名单 | ✅ git status 核对本会话仅改上述 5 个文件 |

遗留提示（供主代理）：① 升级模块后 seen_map 才生效；② 若库中存在系统参数
edu.portal_hidden_cards 会覆盖任务4的默认值；③ roles.py 旧路由仍在但被叶子类覆盖，属预期。
