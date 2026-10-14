# 实施代理 PF · 档案动作族组（缺口 B7，exec_PF）

日期：2026-08-23　范围铁律：仅动 `edu_portal/controllers/batch1.py`、`views/batch1.xml`、新增 `models/profile_extra.py`、`security/ir.model.access.csv`（追加行）。未执行 docker/odoo/curl。

## 缺口回顾
B7：原站学生档案页（oe_student_portal_div）有五个交互动作——添加技能、Placement Offer 加入/拒绝、请假撤回、费用 PDF 下载、道歉信提交；本地档案页七个锚点分区几乎全为「暂无…记录」空态，无任何写入口。本组按「每件 = 表单/按钮(POST+csrf) + sudo 控制器(归属校验) + ?saved=1 横幅 + 空态」补齐。

## 改动清单

### 0. custom_addons/edu_portal/models/profile_extra.py【新增】
- `edu.student.skill(name Char128 required, student_id m2o op.student required index ondelete=cascade)`；`_order=create_date desc`。
- `edu.placement.offer(student_id m2o op.student required index, title Char256, company Char256, state Selection[invited/joined/rejected] default=invited index)`。
- 不加 `_sql_constraints`/`name_get`（Odoo19 兼容性从简）；同名去重放控制器层做。
- **⚠ 范围注记**：为使新模型可被加载，在 `models/__init__.py` 追加了唯一一行 `from . import profile_extra`——这是 Odoo 注册 Python 模型的唯一机制（manifest 无 models 键），属任务所述「models 导入注册」的必要落点，未触碰其它任何模型文件。

### 0b. security/ir.model.access.csv（追加 4 行）
- `edu.student.skill` / `edu.placement.offer` 各 portal(1,0,0,0)+user(1,1,1,1)。门户只读、写路径全部走控制器 sudo+归属校验，与 edu.leave/edu.grievance 既有 ACL 策略一致。`__manifest__.py` 未改：csv 与 batch1.xml 本就在 data 列表内，无需新注册。

### 1. B7-1 添加技能
- 控制器 `POST /my/skill/save`（csrf=True）：strip+截断128 → 本人已有技能 lowercase 集合查重（dup→`?error=skill_dup`）→ create `{name, student_id}`。
- 模板「技能测评」卡：chips 渲染本人技能（复用 oe-adm-chip 样式），无技能时空态文案改为引导语，卡片底部常驻 "Add Your Skill" 内联小表单（hidden csrf_token）。

### 2. B7-2 Placement Offer 加入/拒绝
- 控制器 `POST /my/offer/set_state {offer_id, action}`：browse+exists → `offer.student_id.id != student.id` 即拒（offer_missing）→ 仅 `action∈{join,reject}` 且 `state=='invited'` 可变更（否则 offer_state）→ write joined/rejected。
- 模板 placement_offers 区：本人 offer 卡片列表（标题/公司/状态徽章 invited-info/joined-success/rejected-danger），invited 行内两枚 POST 小表单按钮「加入」「拒绝」；无记录保留原「暂无放置记录」空态。
- **后台录入 offer 不在本任务范围**（铁律禁止动其它模块/后台视图）；数据可经开发者模式或后续批次录入，页面空态与有数据均已适配。

### 3. B7-3 请假撤回
- 先读 models/leave.py 确认：edu.leave.state ∈ {request, approved, refused}，**无独立取消态**。故撤回语义 = 置为既有终态 `refused` 并在 `reject_reason` 写入「学生本人于学生档案页撤回该申请。」留痕（管理员驳回同样要求填原因，二者共用状态值但原因可区分）。
- 控制器 `POST /my/leave/withdraw {leave_id}`：归属校验同上；`state != 'request'` 一律拒绝（leave_state）——已审批(approved)/已拒绝(refused)不可撤。
- 模板 personal_info 区新增「请假记录」卡（家长信息与成就之间）：本人最近 5 条 leave（类型中文映射/起止日期/状态徽章），仅 request 行渲染「撤回」按钮（POST 表单 + confirm 二次确认）；无记录空态「暂无请假记录」。

### 4. B7-4 费用 PDF
- 控制器 `GET /my/invoice/pdf/<int:move_id>`：sudo browse account.move → 校验 `move_type=='out_invoice'` 且 `move.partner_id == student.partner_id`（越权按 invoice_missing 处理）→ `ir.actions.report._render_qweb_pdf(ref,[move.id])`，ref 先试 xmlid `account.account_invoices`、异常回退报表名 `account.report_invoice`（与本仓 batch3 证书 PDF 同款调用方式）→ 成功返回 `application/pdf`（attachment，文件名 ASCII 清洗）。
- 兜底：两次渲染皆失败 → 重定向回档案 fees tab 带 `?error=pdf_fail` 友好横幅，绝不抛 500。
- 模板费用表头尾各加一列「操作」，每行「下载PDF」链接按钮；空态不变。控制器 fees 数据行补 `'id': inv.id`。

### 5. B7-5 道歉信
- 复用 edu.grievance（category 为自由 Char，固定写入「道歉信」），编号沿用 `/my/grievances/save` 的 `GRI%04d` 递增惯例，state=submitted。
- 控制器 `POST /my/apology/save {subject, description}`：subject≤200、description≤2000，任一为空 → apology_empty。
- 模板 discipline 区追加「道歉信」卡：本人 category=道歉信 最近 5 条历史（日期/主题/状态徽章）+ 空态 + 内联小表单（主题/说明/提交按钮）。

### 公共改动（batch1.py / batch1.xml）
- batch1.py：模块级新增状态文案/徽章映射、`PROFILE_TABS` 白名单、saved/error→横幅文案映射、`_back_to_profile()` 重定向助手、`_post_int()` 安全取整、`import re`；`student_profile` 解析 `saved/error/tab`（白名单校验）生成 `banner_text/banner_kind/tab` 并装配 skills/offers/leaves/apologies 四组本人数据（全部 `[('student_id','=',student.id)]` 域过滤）。
- batch1.xml：档案页顶部新增横幅区（alert-success/warning/danger）；七个导航项与七个 pane 改由 `tab` 变量驱动 Bootstrap active/show（动作后重定向自动落回对应分区）；所有 POST 表单均含 `<input type="hidden" name="csrf_token" t-att-value="request.csrf_token()"/>`。

## 安全自查
- 五路由中四个写路由均 `methods=['POST'] + csrf=True`；PDF 为只读 GET。
- 归属校验：skill/offer/leave 以 `record.student_id.id == current_student().id`；invoice 以 partner 相等 + out_invoice 限定；apology 创建时 student_id 强制取当前学生，不接受任何越权字段。
- 全部取数 sudo 但先过归属域；越权一律重定向+横幅，不泄露记录存在性之外的差异信息。

## 自检结果
- `python3 -m py_compile controllers/batch1.py models/profile_extra.py models/__init__.py` ✅
- `xml.etree.ElementTree.parse('views/batch1.xml')` ✅；access csv 实际数据行均 8 列 ✅（文件内原有空行为历史格式，Odoo CSV 加载器跳过）
- 未执行 docker/odoo/curl；未触碰 batch2/batch3/roles 及其它模块（除上述 __init__.py 一行注册注记）。
