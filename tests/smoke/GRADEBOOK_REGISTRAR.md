# 教务在「成绩簿」页给学生录分 —— 交付与判据报告（task-18）

> 日期：2026-10-03 ｜ 作者：task-18 子代理 ｜ 状态：**本地已交付并实测通过；未部署生产**（部署须用户确认）
> 用户原话：「我希望教务人员的这个成绩薄页面，可以改成给学生录入成绩。」
> 相关：`docs/research/gradebook-entry.md`（附录 A：同类先例 + 查重）、`tests/smoke/GRADE_ENTRY.md`（录入引擎本身的交付报告）

---

## 0. 一句话

**教务打开 /grade-book 拿到的现在是整班成绩录入网格**（不再是「该页面仅面向学生账号」的拒止文案）；
在**这个页面上**录的分，学生端 /grade-book **即时可见**，并且与后台「考试参加者 / 结果行」是同一份数字。

---

## 1. 改了什么

| 文件 | 改动 | 说明 |
|---|---|---|
| `custom_addons/edu_portal/controllers/grading.py` | **新增**（约 60 行，含注释） | 用 Odoo 19 官方的控制器覆写机制（`odoo/http.py` 的 `Controller` 文档字符串："inherit from its class, override relevant methods and re-expose them with route()"；实现见同文件 `_generate_routing_rules()`：取继承树**叶子类**、各层 @route 参数**自祖先向子孙合并**）把 /grade-book 按身份分流 |
| `custom_addons/edu_portal/controllers/__init__.py` | +3 行 import | 新控制器文件必须被 import 才会注册（**超出任务声明的可写范围，在此点名**）；必须排在 `grade_entry` 之后 |
| `tests/smoke/gradebook_registrar_entry.py` | **新增** | 端到端页面探针（20 条断言：真点击录分 → 学生端页面同步 → 还原；含反向对照与控制组） |
| `tests/ui/surface.json` | /grade-book 的 roles 补 `backoffice` / `admin`，补 evidence | 让登记表反映新行为；**未加 accessibility gate**（理由见 §4） |
| `docs/research/gradebook-entry.md` | 追加附录 A | 铁律 0 记录：同类先例（沿引本文 §5.1.6 / §5.2 的源码级取证）+ 查重结论 + 本轮取证边界 |

**没碰的文件**（一个字节都没改）：`controllers/batch2.py`、`views/batch2.xml`、`controllers/roles.py`、`controllers/grade_entry.py`、`views/grade_entry.xml`、`models/menu_labels.py`。
其中 `batch2.py` / `batch2.xml` / `roles.py` 是 **task-19 正在改的共享文件**（工作区里已有它未提交的 89 行改动），
用「控制器覆写」而不是直接改 `/grade-book` 的宿主文件，正是为了不与它互相覆盖。

## 2. 页面级判据（Playwright 真点击，采集 2026-10-03 16:5x）

入口：`/opt/homebrew/bin/python3 tests/smoke/gradebook_registrar_entry.py`（结果落盘 `tests/smoke/gradebook_registrar_entry_results.json`）
读数：**20 / 20 PASS，0 FAIL**。关键几条：

| 断言 | 读数 |
|---|---|
| B2 教务 GET /grade-book | HTTP **200** |
| B3 教务看到的是「成绩录入」而不是拒止文案 | 含「成绩录入」=True；含「该页面仅面向学生账号」=**False** |
| B4 班级下拉 | 18 个 option（教务 = 全校班级） |
| B5 选班后出现网格 | 格子数 **56**（整班 × 全部科目） |
| B6/B7 科目筛选页定位 (王小明 × 小要理问答) | 找到输入框；原值 74 |
| C1/C2 点「保存成绩」 | 出现「已保存」；页面回显新值 83 |
| C3 库内两侧 | attendee=**83** 与 result_line=**83**（同一个值） |
| **C4 学生端 /grade-book 页面** | 该生「小要理问答 · 第一学期 总评」行显示 **83**（页面文本，不查库） |
| C5 学生端形态未变 | 仍含「成绩簿」、不含「成绩录入」 |
| R1–R4 还原 | 库内两侧回到 74；学生端页面也回到 74 |
| R3 存量演示行 | EX-DEMO-01 的 attendee 全程 20 → 20 |
| D1/D2 对照 | 教师 / 家长在 /grade-book 上**仍是原拒止文案**（分流是按身份，不是全局） |
| E1/E2 控制组 | 未登录 → 落到登录页；不存在班级 → 200 空表单（不 500、无 Traceback） |

## 3. 回归与门禁

| 项 | 命令 | 读数 |
|---|---|---|
| 录入引擎本身没被改坏 | `python3 tests/smoke/grade_entry_probe.py` | **44 条断言 / 失败 0**（含越权、脏数据、控制组、存量不动） |
| 模块升级 | `bash scripts/safe_upgrade.sh edu_portal` | **EXIT=0**，无失败特征；日志 `/tmp/edu19_upgrade.20261003-164738.log` |
| UI 面登记 | `python3 scripts/check_ui_surface.py` | exit 0 |
| 继承 xpath | `python3 scripts/check_view_xpath.py` | exit 0 |
| 汉化 must-fix | `python3 scripts/check_english.py` | exit 0 |
| 路由 × 角色矩阵 | `python3 tests/smoke/ux_v3_route_matrix.py` | 检查点 540：**PASS 540 / FAIL(真红) 0** |
| Markdown 表格 | `python3 scripts/check_md_tables.py` | exit 0 |
| 全量门禁 | `bash scripts/check_all.sh --fresh-install` | **通过 29 / 失败 4**（2026-10-03 16:52–17:04）。4 项红**全部落在并发窗口**里 —— 同一时段 `/tmp/edu19_upgrade.2026*.log` 有 4 次升级（16:55:54 / 16:56:33 / 16:58:30 / 17:00:01）且 web 容器重启（**task-19 子代理在并行改 edu_portal**）：`accessibility` exit=3 且脚本自己打「并发状态：busy」、`ui_usability` exit=2(ENV)、`metric_consistency` 与 `write_error_paths` 都是 Playwright 导航超时。**安静窗口逐条重跑（17:04:33–17:08:35）：四项全部 exit=0**（accessibility 72 页 0 违规、ui_usability 0 命中、metric_consistency 各指标极差 0.00、write_error_paths 空载荷全被挡）⇒ **本卡有效读数 = 33/33 全绿**（其中 4 项为复跑读数，已注明） |

## 4. 已知粗糙边 / 未做 / 待确认

1. **URL 交接**：`/grade-book` 的录入页里，「打开成绩网格」这个 GET 表单的 action 写在**既有模板** `views/grade_entry.xml` 里，指向 `/grade-entry`。所以教务在 /grade-book 上选完班级点开网格后，地址栏会变成 /grade-entry（**同一个网格、同一套引擎**）。要消掉这一跳必须改那个共享模板 —— 超出本卡声明的可写范围，**有意不做**，如实登记。
2. **教师侧未改**（本卡只要求教务）：教师打开 /grade-book 仍是原拒止文案；教师的录入口一直是左侧导航「学习 → 成绩录入」（/grade-entry，按本人任教班级收敛）。**教师是否也应改成同一形态，属产品口径，未自行拍板**（见回报的待确认项）。
3. **「只能录」还是「也能改」未拍板**：既有引擎允许覆盖已有分数（每次改动留痕 `edu.grade.history`：谁 / 何时 / 从多少改到多少）。本轮**没有**加「只能首次录入、不能修改」的闸门 —— 若校方要求教务只能录不能改，需要在保存路径上新增判断。
4. **/grade-book 的无障碍 gate 未加**：教务在 /grade-book 上渲染的 DOM 与 /grade-entry **同源**（同一个控制器方法 + 同一个模板），而 /grade-entry × backoffice 已在 a11y 门禁扫描集内（0 违规）⇒ 本次**没有新增未覆盖的无障碍渲染面**。但 /grade-book 的**学生**视角此前就没有进 a11y 扫描集（`check_accessibility.py` 的取样口径 `AUDIT_ROUTES` 里没有它）；把这条补上属扩覆盖，会让一个此前无人扫的页面进判据，**未在本卡擅自扩面**（已在 surface.json 记 evidence 说明）。
5. **/my/apps 里教务看不到「成绩录入」卡片**（`batch2.py` 的 `_STUDENT_ONLY_CARDS` 反向清单 + 无对应卡片项）—— 教务的入口只有左侧导航。补卡片要改 `batch2.py`（task-19 的写作用域），**本卡不动**。

## 5. 证据文件

| 文件 | 内容 |
|---|---|
| `tests/smoke/gradebook_registrar_entry.py` / `_results.json` | 本轮探针与读数（20/20） |
| `tests/gap/shots/gradebook-registrar/*.png` | 页面截图（教务在 /grade-book 的录入页、整班网格、科目筛选网格、学生端） |
| `tests/smoke/grade_entry_probe_results.json` | 录入引擎回归读数（44/44） |
| `docs/research/gradebook-entry.md` 附录 A | 先例 + 查重 + 取证边界 |
