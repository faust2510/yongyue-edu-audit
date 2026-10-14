# 成绩中心（成绩簿）—— 追溯设计 + 本轮收口

> **状态**：`已上线` ｜ **主题**：`成绩中心（成绩簿）` ｜ **取代**：`—` ｜ **核对**：`2026-10-14`
> 状态说明：设计定案 2026-10-13（三轮访谈 13 问）；本轮三件（xlsx 往返 / 教务手工加人 / 后台「按科目」只读入口）已实现、本地验收 42/42、已部署上生产（§8.4）。
> 决策来源：三轮用户访谈（13 问，2026-10-13）+ `docs/research/gradebook-entry.md` §1.3 的 4 条原拍板
> 前置档案：`docs/research/gradebook-entry.md`（1488 行，调研已完成）
> 关联：`docs/plans/README.md:45`（待办①，本文取代其「设计未开始」口径）

---

## 0. 一句话

**这不是「新建设计」，是「追溯设计」**：成绩中心已有实存实现并在生产上跑着，本文记录**已落定口径 + 本轮收口范围 + 明确不做**。

### 0.1 为什么是追溯（事实，2026-10-13 核实）

| 事实 | 证据 |
|---|---|
| 实现已于 2026-10-03 交付（task-18） | `custom_addons/edu_portal/controllers/grade_entry.py`（620 行）、`custom_addons/edu_portal/controllers/grading.py:56` |
| 审计独立验证 11/11 PASS | `docs/audit/backend-ux/t18-independent-verification.md:4-6`（commit `415d215`） |
| **生产上已在跑** | 本会话实测：`grade_entry.py` / `grading.py` / `views/batch2.xml` 三文件本地与生产 `md5` 逐一相同；生产进程认 `/grade-entry`、`/grade-book`、`/grade-book/report/download`（匿名均 303 去登录，非 404） |
| `docs/plans/README.md:45` 的「🟡 调研完成，设计未开始」**过时** | 同上；本轮已改 |

### 0.2 本文与 research 档案的关系（**4 处矛盾已登记，以本文为准**）

| # | research 档案里的说法 | 实际 | 处理 |
|---|---|---|---|
| 1 | §11（`:1257-1261`）推荐「新建 `edu.grade.*` 表」 | 实存实现**不新建模型**（`grade_entry.py:1-46` 文件头写明「本仓硬口径：不新造成绩模型」），而是复用基座 `op.exam` 容器 + 直写三张基座表 | **以实存为准**（附录 A `:1476` 亦记「本轮不新建模型」）；§11 保留为历史评估 |
| 2 | §8.2（`:1111`）用 8 条否证「把 `op.exam` 伪装成单场考试」 | 实存实现恰恰自建 `op.exam` 容器（`grade_entry.py:134-209`） | 同上；§8.2 的否证针对的是「手工凑考试」，与「程序化建容器」不同 |
| 3 | §0.1 / §2.4（`:16`、`:172-203`）称读写两表「唯一的桥 = 手动按钮」 | 该结论对基座按钮仍成立，但 `/grade-entry` 已**旁路**：门户把两侧写齐（`grade_entry.py:593/602/607`） | §3 结论仍有效，但不可据此判断「学生仍看不见」 |
| 4 | §4.3 / §9.1 / §14.5 引用 `batch2.py:1034-1093` | 该文件已被本会话 commit `eb19918` 改动（2174 行），路由现于 `batch2.py:1069` | 引用需重定位 |

**推论**：research §13（`:1314-1329`）的 10 项待拍清单里，Q1/Q2/Q3/Q5/Q6 的答案已被代码选定，Q7 的提问对象已消失 —— 本文 §2 是它们的最终口径。

---

## 1. 用户拍板（13 条，2026-10-13 三轮访谈）

原 4 条（`docs/research/gradebook-entry.md:71-78`，2026-09-24 队长转达）：**一科一个总分**（否决 `op.exam` 作主结构）｜**教务 + 任课老师都能录**｜**录完即见、不需要发布**｜**名单按报课记录**。

本轮新增 9 条（全部选推荐项）：

| # | 决策 | 口径 |
|---|---|---|
| 1 | **元问题** | **追认现有实现**，不返工 620 行、不打断已验通的学生端链 |
| 2 | **容器污染** | **接受**：后台「考试」菜单会出现 `GE_` 容器考试 —— 登记为已知取舍，不额外做过滤 |
| 3 | **谁能改** | 教务 + 任课老师**都能录都能改**，谁后改谁生效，靠 `edu.grade.history` 留痕追责（**现状已是**） |
| 4 | **成绩粒度** | **一学期一科一行**（**现状已是**） |
| 5 | **评分制** | 录**百分制自动映射七档**（**现状已是**）；映射函数必须**只写一处**（见 §5） |
| 6 | **名单口径** | **报课为主 + 教务可手工加人** —— 手工加人是**必须做**（见 §4.2），不是可选项 |
| 7 | **填完标记** | **不做**「我这一栏填完了」动作（无发布态是刻意取舍） |
| 8 | **变更历史页** | **二期做**（用现有 `/grading/history` 扩三筛） |
| 9 | **旧成绩行** | 重录同（班,学期,科目）时**同一行 UPDATE**；生产 `op_result_line` 0 行，不迁移 |
| 10 | **交付面** | 最小闭环 + **xlsx 导入导出**；统计与成绩单 PDF 留后 |
| 11 | **入口** | **门户为主**（`/grade-book` 两态已实现）+ **后台也挂「按科目」入口**（本轮做） |
| 12 | **教师分派** | 本期**只交付教务侧**；`op_session.faculty_id` 分派登记为**运营待办**（用后台现成列表 / xlsx 导入改，不新写页面） |
| 13 | **学期锚点** | **接受日期区间判定**默认学期（录入页可改选）；不加「当前学期」开关 |

---

## 2. 已落定口径（现状实现地图，改动前必读）

### 2.1 数据链（为什么能「录完即见」）

```
门户录入  /grade-entry  →  /grade-entry/save
   │
   ├─ ① 按需 get-or-create 容器链（幂等）
   │     op.exam.session（一学期 × 一班）
   │     op.exam（该班一科一个总分，exam_code = GE<batch>S<subject>T<term>）
   │     op.result.template + op.marksheet.register
   │     ← controllers/grade_entry.py:134-209（_ensure_container）、:67（_code）、:109（_free_slot）
   │
   ├─ ② 写侧：op.exam.attendees.marks → edu.grade.history.edu_apply_marks()（唯一受管入口，含站内信）
   │     ← grade_entry.py:593、models/registration.py:631-662
   │
   └─ ③ 读侧：把同一个值写进 op.marksheet.line + op.result.line
         ← grade_entry.py:602、:607 ⇒ 学生页 /grade-book、/my/study、/users/result-overview 即时可见
```

**不要走**基座 `op.result.template.generate_result()`（`openeducat_erp/openeducat_exam/models/result_template.py:73-101`）：它按一次就把数据锁死（`op.result.line` 有 `UNIQUE(exam_id, student_id)`）。

### 2.2 名单（`_roster`，`grade_entry.py:259-306`）

现状两条并存：① **班级名单**（`op.student.course` 有 `batch_id`，标 `source='班级'`）∪ ② **报课且未分班**（`subject_ids` 含本科且 `batch_id` 为空，标 `source='报课（未分班）'`）。本轮新增 ③ 手工加人（§4.2）。

### 2.3 权限（四层模型第 2/3 层）

- 教务 / 超管 = 全校；任课教师 = **本人任教 (班级 × 科目)**，判据 `op.session(faculty_id, batch_id, subject_id)` 三元组（与 `roles.py:842-855` 的 `_teacher_exam_domain()` 同粒度）。
- **数据层不收敛**：`op.exam*` 无行级规则；`op.marksheet.line` / `op.result.line` 的 4 条规则全挂同一组、Odoo 19 组规则是**并集** ⇒ 收敛必须写在**写入路径**上（`grade_entry.py:509-617` 会按登录身份重算可写集合，POST 的 `batch_id`/`subject_id`/学生 id 一律不信任）。
- 正确写法抄本：`custom_addons/edu_assess/security/security.xml:74-94`（补恒真域，避免跨组 OR 把教务误收敛成零行）。

### 2.4 入口

| 入口 | 位置 | 形态 |
|---|---|---|
| 门户卡片「成绩簿」 | `roles.py:427` → `/grade-book` | 教务/超管 = **录入态**；学生 = 成绩簿；教师/家长 = 拒止文案（`grading.py:56` 裸 `@http.route()` 覆盖 `batch2.py:1069`） |
| 独立录入页 | `/grade-entry`（`grade_entry.py:408`） | 模板 `views/grade_entry.xml:12`（`edu_grade_entry`），manifest `__manifest__.py:128` |
| 后台「按科目」 | **本轮新增**（§4.3） | 只读列表 + 菜单 + 跳录入页 |

### 2.5 留痕

`custom_addons/edu_portal/models/registration.py:594-662`：`edu.grade.history`（`exam_id`/`student_id`/`subject_id`(related store)/`old_marks`/`new_marks`/`action`/`source`/`logged_user_id`/`timemodified`/`note`），唯一写入口 `edu_apply_marks()`。ACL 见 `views/notice_admin.xml:286-314`。

---

## 3. 生产读数（2026-10-13 06:15 UTC，只读）

| 项 | 读数 | 含义 |
|---|---|---|
| `op_exam` | **0 行**；`op_exam_type` 只有 `1\|阶段考\|SES` | 生产**从未用过** `/grade-entry`；教务第一次保存会新建 `TERM` 类型 + 容器（已获拍板 #2 授权） |
| 学生 | `op_student` 51 / `op_student_course` 45 | **6 名「待分配」学生完全没有 `op.student.course` 行**（id 25/30/39/40/54/56）⇒ 现状永远进不了任何成绩网格 ⇒ **手工加人必须做** |
| 教师 | `op_faculty` **1 行**「待定」（`id=20`、`active=f`、`user_id=33`）；`op_session` **216 节全挂它**（5 班 / 18 科） | 「教师能录」今天 = teacher@local 一人可改全校 18 科 ⇒ 拍板 #12 登记为运营待办 |
| 规模 | 最大班 10 人（batch 13）；科目最多的班 = 总览班 batch 34（14 科）；常量 `MAX_MARKS=100`/`MIN_MARKS=60`/`MAX_COLUMNS=20`（`grade_entry.py:48/49/51`） | **不触发截断**（总览班已用 70% 配额）；总览班 0 学生 ⇒ 现状是空网格（手工加人可解） |
| 学期 | `op_academic_term` 只有 `term_start_date`/`term_end_date`，**无「当前学期」字段**；第一学期 `2026-06-23~2026-12-20` | 今天落在第一学期；判定靠日期区间（`grade_entry.py:75-86`），已获拍板 #13 接受 |

---

## 4. 本轮交付范围（3 件，其余不动）

### 4.1 W1 · xlsx 导出 / 导入（教务批量录分）

- **形态**：**导出自解释表**（首行含 `班/学期/科目`，数据列 `学号 | 姓名 | 分数 | 等级`），**导入走同一条 save 路径**（`_ensure_container` + `edu_apply_marks` + 双写），**不新写第三套录入口径**。
- **为什么不直接用 `base_import`**：基座两个模型的 `exam_id`/`student_id` 必填 ⇒ 原生导入必须带内部 id，教务无法「凭空一科一个总分」；且原生写绕过留痕与双写 ⇒ 学生看不见（正是本次要修的断点）。
- **导入必须回报逐行结果**：成功 / 学号未匹配 / 分数超范围（`0..100`）/ 该身份无权录该（班,科目）。

### 4.2 W2 · 教务手工加人（名单第 ③ 条来源）

- **必须做**：6 名「待分配」学生（§3）与总览班 0 学生场景，否则这些人**永远无法出现在任何成绩单上**。
- **口径**：加人 = 在 (班, 学期, 科目) 的名单上落一条**快照行**（新模型），**不改学生档案**（`op.student.course` 不写、不越权）。
- 加过人的名单在后续打开录入页时**仍可见**（不能只在当次会话有效）。

### 4.3 W3 · 后台「按科目」入口

- 后台菜单 + **只读**成绩列表（按 学期 / 班 / 科目 筛选）+ 一个「打开录入页」按钮跳门户 `/grade-entry?batch_id=&subject_id=`。
- **只读是硬约束**：后台上直接改 `op.exam.attendees.marks` 会绕过留痕与双写 ⇒ 学生看不见、且查不到谁改的。

---

## 5. 明确不做 / 已知取舍

| 项 | 理由 |
|---|---|
| 不新建 `edu.grade.*` 成绩表 | 拍板 #1 + 文件头硬口径（`grade_entry.py:1-46`） |
| 不做「填完/发布」态 | 拍板 #7 + 原拍板「不需要发布」；代价：教师填一半学生就能看到（生产最大班 10 人，窗口短） |
| 不做变更历史 UI | 拍板 #8（二期）；留痕数据已齐，只是没有界面 |
| 不做统计（区间/排名/及格率）与成绩单 PDF | 拍板 #10 留后 |
| 不在后台做可编辑列表 | §4.3（会绕过留痕 + 双写） |
| **不统一两处等级映射**（本轮） | 现存两个口径：`openeducat_exam/models/marksheet_line.py:74-87` 用 `percentage` 比阈值，`result_line.py:55-71` 用原始 `marks` 比阈值（**转引 research §10，未亲自复核**）。本轮**不改基座**，只在自研侧固定一处映射函数并在文档登记为债 |

---

## 6. 运营待办（不是代码活，交付时须告知用户）

1. **教师分派**：建真实 `op.faculty` 行 + 把 216 节 `op_session.faculty_id` 分派到真实教师（拍板 #12）。未做之前，教师侧只有 teacher@local 一个账号可用。
2. **6 名「待分配」学生**：决定他们归哪个班（或长期靠手工加人）。
3. **首次保存的容器**：教务第一次保存会在生产新建 `TERM` 类型与 `GE_` 容器考试（已授权）。

---

## 7. 验收标准（本轮）

| 层 | 断言 |
|---|---|
| 升级 | `bash scripts/safe_upgrade.sh edu_portal` 无失败特征 |
| 门禁 | `check_odoo_trace.py` / `check_english.py` / `check_view_xpath.py` / `check_alias_not_extended.py` 全绿 |
| 活体 · 身份 | 教务/超管 `/grade-entry` = 200 且渲染网格；学生/家长 = 303 回门户 |
| 活体 · 双写 | 保存后 `op.exam.attendees.marks` == `op.result.line.marks` == `op.marksheet.line` 同值（**学生看得见**） |
| 活体 · 留痕 | 每次保存/导入在 `edu.grade.history` 落行，含 `old_marks`/`new_marks`/`logged_user_id`/`source` |
| 活体 · 加人 | 给 6 名「待分配」学生中任一人加进 (班,学期,科目) 名单并保存 ⇒ 学生页可见；重开录入页名单仍在 |
| 活体 · xlsx | 导出→原样导入 = 幂等（值不变、**不重复留痕** —— 沿用 `edu_apply_marks`「无变化不留痕」语义，结果页标「无改动（已是最新值）」，见 §8.2）；改一个分数再导入 ⇒ 该生学生页数字随之变 |
| 越权 | 教师 POST 非本人 (班,科目) 的学生 ⇒ 整条丢弃（不落库、不报 500） |

---

## 8. 实测与债（2026-10-13 本地闭环）

### 8.1 活体验收（`tests/smoke/gradebook_center_io.py`，**42 / 42 PASS**）

| 组 | 关键读数 |
|---|---|
| W1 xlsx | 目标 = 预备科 · 2026级【演示】/ 第一学期 / 小要理问答（batch 8 / term 1 / subject 35，名册 4 人）；导出自解释表首行 `班/学期/科目`、次行 `学号|姓名|分数|等级`；**原样导入 → 实际写入 0 条**、结果页标「无改动」；把 DUP-001 的 80 改成 81 再导入 → **写入 1 条**、`edu_grade_history` 新增 `source=import / new_marks=81`、**再导出 = 81**（与「学生端可见值」同源）；原表导回 → **80**（自还原） |
| W2 加人 | 教务 add-student → `added=1`、`edu_grade_entry_extra` 落行、`edu_audit_log` 新增「手工加人」、`op_student_course` 行数不变（没碰学籍）；教师侧：卡片不渲染、**仍看得见被加的人（③ 标记）**、add/remove 均 `err=scope` 且数据未变；学生 add/remove/export/xlsx 全部 303 `/my/home`；教务 remove → `removed=1`、快照行删除 |
| W3 后台 | 容器列表 arch 含 `create/edit/delete="false"`、`view_mode` 只有 `list`、domain 带 `GE`；「成绩中心」菜单**只挂教务 / 超管两组**；教务 `/odoo/action-863` = 200 且 `load_menus` 含「成绩中心」，教师 `load_menus` **不含** |

门禁全绿：`check_view_xpath`（失败项 0）/ `check_alias_not_extended`（OK）/ `check_ui_surface`（违规 0）/ `check_manifest_order`（PASS）/ `check_manifest_tracking`（OK）/ `check_english`（must-fix 0 · brand 0 · 路由违规 0 · 夹具残留 0，`/grade-entry` 真实渲染 200）/ `check_odoo_trace`（PASS，52 条静态路由全部已验证）。
`tests/ui/surface.json` 用 `ui_surface_report.py --generate` 重生成（补上本轮新路由，以及 P1 轮遗留的 `/web`、`/odoo`、`/odoo/<path:subpath>`、`/scoped_app/<path:subpath>`）。

### 8.2 口径订正（与 §4.1 原稿的差异，**以此处为准**）

1. **「原样导入留痕新增行」不成立**：`edu.grade.history.edu_apply_marks` 的既定语义是「值未变 → 不写留痕」，本轮**不改它**（改掉会破坏「无变化不留痕」这个更有价值的意图）。导入结果页把这类行如实标成「无改动（已是最新值）」，不谎报成功。
2. **导入逐行状态实际 8 种**（原稿点名 4 种）：成功 / 学号未匹配 / 分数超范围 / 该身份无权录该（班,科目）/ 未填分数（跳过）/ 学号重复（跳过）/ 分数不是数字（跳过）/ 无改动。
3. **多了两处保护**（实现者提出、调度者接受）：① 首行 `班/学期/科目` 与当前目标不一致 ⇒ **整表拒写**（防「导错班」静默写错人）；② `/grade-entry/xlsx` 页 + 后台「批量导入 / 导出（xlsx）」菜单 —— 否则 W1 没有任何入口。
4. **「等级」列只导出不导入**（导入只按 学号 + 分数 写）—— 避免出现第三处等级映射。

### 8.3 债（登记，不阻塞本轮）

| 债 | 位置 | 说明 |
|---|---|---|
| 读侧双写被复刻 | `controllers/grade_entry_io.py:148 _sync_read_side` | 与 `/grade-entry/save` 路由体里的双写同口径但**不是同一个函数**（那段内联在路由里，抽不出来）。两处必须同改；抽成公共函数后应改为 import |
| 后台只读只能靠视图 | `views/grade_admin_views.xml:43` | ACL 挡不住（教务组实测带 `op.exam` perm_write=1），只读靠 `create/edit/delete=false` + 不给 form 视图 |
| 学期没有可筛字段 | `views/grade_admin_views.xml:63` | `op.exam` / `op.exam.session` 无 term 字段 ⇒ 后台按「成绩单」（名字 = 学期 · 班 成绩单）筛 / 分组，不给基座加字段 |
| 门禁抓不到 RNG 语义 | `scripts/check_view_xpath.py` | 本轮 `<group expand="0">` 静态全绿、真升级才炸（Odoo 19 的 search view 不接受 `expand`/`string`）。建议加一条可选的 lxml RelaxNG 规则（用 Odoo 自带 `base/rng/*.rng`） |
| 等级映射两处口径 | 基座 `marksheet_line.py` / `result_line.py` | §5 已登记；本轮只在自研侧固定一处映射函数 |

### 8.4 生产部署（2026-10-13）

- `bash scripts/deploy_myedu.sh edu_portal` → **DEPLOY_RC=0**（升级无失败特征 → web 已重启就绪 → 匿名冒烟全绿 → 活体注册表门禁 115/115 LIVE、0 DARK）。
- 11 个改动文件远端 md5 与本地逐一相同；生产库已有 `edu_grade_entry_extra` 表 + `edu.grade.entry.extra` 模型登记 + 容器列表视图 / 搜索视图 / 「成绩中心」菜单 / `GE_` 域 action 各 1 条；匿名 `/grade-entry`、`/grade-entry/xlsx`、`/grade-entry/export.xlsx`、`/grade-book` 均 303 → 登录页（跑着的进程认识这些路由）。
- **未验证**：登录态路由与页面 —— 仓库里没有生产账号（同 `docs/audit/deploy-2026-10-03.md:55` 的既有局限），部署脚本也自报此警告。⇒ 教务侧「导出 / 导入 / 加人」与后台「成绩中心」菜单**需要在生产上用真实账号目视一次**。


