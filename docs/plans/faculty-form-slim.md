# 教职员工（op.faculty）表单瘦身 — 设计与证据
> **状态**：`已上线` ｜ **主题**：`教职员工表单瘦身` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「未部署生产」，实际已于 2026-09-24 部署上线（生产 `faculty_form.xml` 与本地 md5 一致，web 进程 2026-09-24 22:29 重启后已加载）——2026-09-26 核对发现。正文未改动。

状态：**本地 clone 已实现并验收通过（未部署生产）**｜日期：2026-09-24｜任务：A（表单瘦身）

## 1. 背景

校长打开 `/odoo/faculty/new`（菜单 259，已由 `views/menu_labels.xml` 改名「教职员工」）后说：
「我不知道后面搞那么多无关的信息干嘛」。该表单是 OpenEduCat 的**人事档案**，把 HR 字段
（血型/紧急联系人/签证/身份证/HR 员工/用户/伙伴/国籍/完整地址/联系人看板）和**图书馆页签**
全摊在第一屏 —— 一个语言学校的职员要建的只是「这位老师是谁、教什么、怎么联系」。

## 2. 决定（做什么 / 不做什么）

| 处置 | 字段 |
|---|---|
| 首屏保留 | 姓名 first/middle/last、性别 gender、出生日期 birth_date、所属院系 main_department_id、邮箱 email、电话 phone；科目 faculty_subject_ids（默认展开的「科目」页签） |
| 收进「更多信息」页签 | 血型 blood_group、紧急联系方式 emergency_contact、身份证号 id_number、签证信息 visa_info、国籍 nationality、人力资源员工 emp_id、用户 user_id、伙伴 partner_id、允许的院系 allowed_department_ids、语言 lang、称谓 title、头像 image_1920、地址 6 件（street/street2/city/state_id/zip/country_id） |
| 整页移除 | 图书馆页签（openeducat_library 的 Library page）＋「媒体」统计按钮；基座「Other Information」页签（伙伴联系人看板 = 地址簿噪音） |
| 保留不动 | 「课次」（Sessions）统计按钮（教学信息，不在收单里）；**模型、字段、数据、表列一行未删** |

**「允许的院系」为什么藏**：本地 `op_department` 0 条；该字段只在多院系场景下把
`allowed_department_ids` 抄进用户的 `department_ids` 作授权范围（`openeducat_core/models/res_company.py:59`），
基座自己就把它挂在 `group_multi_department` 下 —— 单院系小学场景留它在首屏只会误放宽权限。
同时本文件顺手修了两件基座毛病：① `main_department_id` 原来挂 `group_multi_department`，
教务组不在该组 ⇒ **所属院系根本看不见**（`faculty_view.xml:66`）；② 标签统一成教务处嘴里的
「所属院系」（模型串/PO 是「主要部门」）。

## 3. 实现

- 视图：`custom_addons/edu_portal/views/faculty_form.xml`（继承 `openeducat_core.view_op_faculty_form`，
  priority 90 > library(16)/timetable(12)，保证 xpath 命中它们加的页签）
  · :51 `//sheet/group` replace = 首屏字段区 · :66 图书馆页签 · :69 媒体按钮 · :74 联系人页签 ·
  :77 在「科目」之后插入 `more_info` 页签（notebook 只渲染当前页签 ⇒ 噪音页签放第一位＝首屏还是噪音）
- manifest：`custom_addons/edu_portal/__manifest__.py:101`
- **零模型改动**：不碰 `openeducat_erp/**`（官方快照）、不碰 edu_telegram。
  还原＝把本文件从 manifest 去掉（或整段注释）后 `-u edu_portal`，表单立刻回基座原样。

## 4. 验收证据（backoffice@local 真浏览器 + ORM 反查）

`python3 tests/smoke/faculty_form_slim.py [--phase before|after]`（17 条判据，after 全绿）；
证据 JSON：`tests/smoke/faculty_form_slim_before.json` / `faculty_form_slim_after.json`

- **改造前首屏可见 22 个字段**：birth_date, blood_group, child_ids, city, country_id, email,
  emergency_contact, emp_id, first_name, gender, image_1920, lang, last_name, middle_name,
  nationality, partner_id, phone, state_id, street, street2, title, user_id, zip；页签＝其他信息(默认)|科目|**图书馆**
- **改造后首屏可见 9 个字段**：first_name, middle_name, last_name, gender, birth_date,
  main_department_id, email, phone（+ faculty_subject_ids）；页签＝科目(默认)|更多信息；
  收起的字段**在首屏 DOM 里都不存在**，点开「更多信息」全部重现
- **只填可见字段能存**：UI 填 姓名/性别/出生日期/邮箱/电话/所属院系/科目 → 保存无
  「Missing required fields」，记录 `op.faculty 212 【演示】李慧 老师`（ORM 反查：
  main_department_id=[12,【演示】中文部]、faculty_subject_ids=[35]）
- **藏而不是删**：DB 列仍在（blood_group/id_number/visa_info/emp_id/...）；记录 212 写
  `blood_group='A+'`、`id_number='【演示】ID-0001'`、`visa_info='【演示】旅游签'` 并读回成功（教务身份即可读写）
- **回归**：backoffice_reachability.py PASS 101/FAIL 0（exit 0）；department_path.py FAIL 0（259→action 388 正常）；
  check_view_xpath OK / check_manifest_tracking OK / check_qweb_dict_foreach OK / gate_seam_check PASS /
  check_english must-fix 0。与本次无关的红：check_odoo_trace 命中 1 处（mail.template 数据面待修项；
  **把本视图关掉后仍是 1 处**，证明与本改动无关）。

## 5. 未验证 / 交接

1. **未部署生产**（按要求）。
2. 「更多信息 → 地址」第二行标签现在显示「学制」—— 那是 `models/partner_edu.py` 的假标签
   （另一个 agent 正在改），本任务没碰；他们 `-u edu_portal` 后自然恢复为地址标签。
3. 更多信息里 `title`/`visa_info`/`allowed_department_ids` 用了视图内中文串（PO 现状：
   「Visa Info」→「查看信息」错译、`user_id`→「销售员」）。若 edu_zh 要统一收口，改成词条即可，
   视图里的中文串可以撤掉。
4. 截图（本次运行）：`/tmp/faculty_form_before_first_screen.png`、`/tmp/faculty_form_after_first_screen.png`、
   `/tmp/faculty_form_after_more_tab.png`。
