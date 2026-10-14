# exec_M — 教师端后台菜单裁剪

实施代理 M（菜单裁剪组）· db=edu19 · 未执行 docker/odoo/curl（铁律遵守）

## 变更清单

| 文件 | 操作 | 内容 |
| --- | --- | --- |
| `scripts/seed_teacher_menus.py` | 新建 | odoo shell 幂等脚本：建组 `edu_portal.group_backend_full`、`base.group_system` 隐含、隐藏名单根菜单 `groups_id += 组`，末尾打印汇总并 commit |
| `custom_addons/edu_portal/controllers/roles.py` | 编辑 | 仅 `apps_menu` 方法内（444–465 行）：`Menu = request.env['ir.ui.menu'].sudo()` → `request.env['ir.ui.menu']`，排序 `order='sequence asc'` 与其余逻辑不变 |

自查：两文件 `python3 -m py_compile` 通过；脚本对组、xmlid 注册、implied、每个菜单写入均先查后写，可重复执行。

## xmlid 核对表

证据来源说明：本机无 Odoo 核心源码（`data/web/addons/19.0` 为空），核对依据为
①`reference/apps_menu_target.html` 与 `reference/enterprise/quiz/list.html`——从 Odoo19+OpenEduCat 目标站抓取的应用网格快照，每张应用卡带 `data-menu-xmlid`；
②`openeducat_erp/openeducat_parent/menus/op_menu.xml:19` 直接定义了 `hr.menu_hr_root`。

| # | 根菜单 xmlid | 中文名 | 本库存在性结论 | 证据 |
| --- | --- | --- | --- | --- |
| 1 | mail.menu_root_discuss | 讨论 | ✅ 存在 | 目标站卡片 Discuss 的 data-menu-xmlid |
| 2 | calendar.mail_menu_calendar | 日历 | ✅ 存在 | 同上（Calendar 卡） |
| 3 | contacts.menu_contacts | 联系人 | ✅ 存在 | 同上（Contacts 卡） |
| 4 | spreadsheet_dashboard.spreadsheet_dashboard_menu_root | 仪表板 | ✅ 存在 | 同上（Dashboards 卡） |
| 5 | account.menu_finance | 发票 | ✅ 存在 | 同上（Accounting 卡） |
| 6 | website.menu_website_configuration | 网站 | ✅ 存在 | 同上；目标站 Website 应用卡即绑定该 Configuration 根菜单 |
| 7 | hr.menu_hr_root | 员工 | ✅ 存在 | openeducat_parent/menus/op_menu.xml 直接定义 + 目标站 Human Resources 卡 |
| 8 | event.event_main_menu | 活动 | ✅ 存在 | 目标站 Events 卡 |
| 9 | hr_recruitment.menu_hr_recruitment_root | 招聘 | ✅ 存在 | 目标站 Recruitment 卡 |
| 10 | im_livechat.menu_livechat_root | 在线聊天 | ✅ 存在 | 目标站 Live Chat 卡 |
| 11 | utm.menu_link_tracker_root | 链接追踪器 | ⚠️ 无本地证据（目标站应用网格也无此卡） | 全仓 grep 无命中。历史版本 utm 该根菜单为 base.group_system 限定、仅调试模式可见，与目标站不显示一致 |

处理：11 项全部保留在脚本 `HIDDEN_MENUS` 中，逐项用 `env.ref(xmlid, raise_if_not_found=False)` + `.exists()` 守卫——缺失自动归入「库中未找到、跳过」汇总行，不会报错；若库中确无该项即等价于跳过。

## roles.py sudo 使用点评估（apps_menu 方法及其直接依赖）

| 位置 | 原状 | 评估结论 |
| --- | --- | --- |
| `apps_menu` L445 `Menu = request.env['ir.ui.menu'].sudo()` | sudo 取全部根菜单 | **已改**：去 sudo。Odoo `ir.ui.menu._search` 会按当前用户 `_filter_visible_menus()` 过滤 groups_id 受限菜单，教师端即被裁剪；管理员因隐含组仍全量 |
| `apps_menu` 循环体内 `m.web_icon / m.name / m.child_id` | 非 sudo 读取 | 无需改：ir.ui.menu 对内部用户可读，且根菜单已通过分组过滤；路由本身 `auth='user'` |
| `_menu_icon_url(m)`（静态方法，方法外） | 只读字段+文件系统 get_module_path | 不涉及 env/sudo，无需改（铁律仅限方法内，亦未触碰） |
| `_menu_href(m)`（静态方法，方法外） | 遍历 `cur.child_id` 找第一个动作做深链 | 未改。注记：child_id 是 One2many 直读、不走分组过滤，理论上被裁剪应用的深链 URL 仍可能被构造出来，但 web 端打开时仍受同一套分组限制，属展示层小瑕疵非越权；如需收紧可在后续迭代给 helper 加可见性过滤 |
| 同文件其它路由的 sudo（notice_publish_save / alumni_job_list / alerts_mark_read 等） | 写操作或跨用户读 | 与本任务无关，均保留 |

## 幂等性要点（seed_teacher_menus.py）

1. 组：先 `env.ref('edu_portal.group_backend_full')`，已存在则校正 name/comment 后跳过创建；新建时手工补 `ir.model.data`（noupdate=True）注册 xmlid。
2. implied：`(4, id)` 前先判 `group.id in sys_group.implied_ids.ids`。
3. 菜单：`groups_id = [(4, group.id)]` 前先判 `group.id in menu.groups_id.ids`；write 触发 ir.ui.menu 缓存清理，前端即时生效。
4. 结果三态打印：新增限制 / 已带限制跳过 / 库中未找到跳过。

## 生效链路

跑一次脚本 → faculty@local（普通内部用户、不在组）访问 `/openeducat/apps_menu` 只见教学类应用卡 → 管理员（base.group_system 隐含）与超管全开 → 给个别用户勾选「后台·完整视图」即可放开。
