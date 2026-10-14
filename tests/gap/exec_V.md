# 实施代理 V — B10 家长代孩子请假挂入口（孤儿页接线）

- 执行人：代理 V（角色组）｜ 约束：仅改 `custom_addons/edu_portal/controllers/roles.py`、`custom_addons/edu_portal/views/roles.xml`；未执行 docker/odoo/curl；未改任何控制器逻辑。

## 缺口定位

- 控制器 `roles.py:313` 已有路由 `['/my/child/<int:child_id>/leave', '/my/child/<int:child_id>/leave/saved']`（GET 表单）与 `roles.py:329` POST `/my/child/<int:child_id>/leave/save`，功能完整可用。
- 全站 grep `my/child`（views/ 目录）：仅 roles.xml 自身 3 处（列表注释、卡片「查看仪表盘」、请假表单返回按钮）——**没有任何链接指向 /my/child/<id>/leave，孤儿页确认**。

## 变更清单（1 个文件，均在许可范围内）

仅改 `custom_addons/edu_portal/views/roles.xml`（roles.py 本任务零改动，只读核对路由）：

1. **`edu_my_child`（/my/child 列表页）每个孩子卡片**：原右侧单个「查看仪表盘」按钮改为竖排按钮组，新增第二个按钮「为孩子请假」→ `t-attf-href="/my/child/#{ kid['student'].id }/leave"`，样式 `btn-outline-primary text-nowrap`，带 fa-calendar-minus-o 图标。入口数：**每个孩子卡片 1 个**（模板级 1 处改动，运行时按孩子数量渲染）。
2. **`edu_child_dashboard`（/my/child/<id> 仪表盘页）头部操作区**：`o_portal_hero` 区块加 `d-flex flex-wrap justify-content-between align-items-start gap-3`，左侧标题/副标题包一层 `<div>`，右侧新增操作按钮组：「为孩子请假」（btn-primary，同路由）+「返回我的孩子」（btn-light → /my/child）。

## 假链接排查（任务第 3 条，逐条记录）

**roles.xml 自身：`href="#"` 出现 0 次。** 全文件 12 个模板逐一核对，所有 `<a>` 均为具体目标（/my/child、lk[0]、/alumni/job/list、/my/home、/my/notice_board/notice 等），无假链接需要清理。

仪表盘「快捷入口」6 个链接目标逐一验证（链接数据源在 roles.py:77-84，渲染在 roles.xml）：

| 链接 | 路由定义 | 结论 |
|---|---|---|
| /student/timetable | main.py:104 | ✅ 真实 |
| /student/attendance | batch1.py:54 | ✅ 真实 |
| /student/exam | batch1.py:263 | ✅ 真实 |
| /grade-book | batch2.py:350 | ✅ 真实 |
| /library/media | batch2.py:413 | ✅ 真实 |
| /my/invoices | Odoo 标准 account 门户路由（batch2 首页分类已在用） | ✅ 真实 |

**越界发现（未改，仅记录）**：`views/batch2.xml` 与 `views/batch3.xml` 共 16 处 `href="#"`（batch2.xml:157/158 媒体采购/媒体运动按钮、:192/:458 卡片名、:425 ghost 按钮；batch3.xml:1109 卡片名、:1245-1257 五个 demo-login-btn、:1330/:1350 创建按钮）。其中 batch3.xml:163/514/1041 三处为 Bootstrap collapse 触发器（data-bs-target 接管，功能正常，不算死链）。其余 13 处为潜在死链——**超出本代理许可文件范围，未动**，建议另开任务处理。

## 自查结果

- [x] 新按钮目标 `/my/child/<id>/leave` 与现有控制器路由（roles.py:313，`<int:child_id>`）逐字符一致；`kid['student'].id` 数据源为 `_child_summary()` 返回的 student 记录，两模板上下文均具备。
- [x] roles.xml minidom/ElementTree 解析通过（XML well-formed）。
- [x] 未执行 docker/odoo/curl；roles.py 及其它任何文件零改动（本会话仅 edit roles.xml 两处）。
- [ ] 运行时冒烟未做（本代理禁 docker）：需由有环境者升级模块后以家长账号验证 /my/child 卡片与 /my/child/<id> 头部按钮可达请假表单。
