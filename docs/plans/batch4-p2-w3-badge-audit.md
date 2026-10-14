# 批次4（P2）W3 角标全站审计留痕
> **状态**：`归档` ｜ **主题**：`角标 0 值审计` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 任务：ux-improve-proposal §W3「角标 0 值灰底与待办聚合规范落实（审计项）」
> 范围：纯视觉/文案层，零业务逻辑改动；只动 `custom_addons/edu_portal`。
> 规范依据：ui-reference.md §6.3「计数角标 0 值灰底（`oe_count_zero`）；红点仅提醒不计数」。

## 1. 全站盘点清单（页 × 角标 × 计数来源 × 结论）

| 页面/位置 | 角标写法 | 计数来源（控制器） | 审计结论 |
|---|---|---|---|
| `/my/home` 首页宫格卡（学生/家长，`edu_one_cat` 普通分类） | `oe_count badge` + `oe_count_zero` 灰底 | `batch2.py _count_for_card`（op.media / op.assignment / edu.fee.bill / 未读布告 / 未读私信等，60s 短缓存；私信实时） | ✓ 已覆盖 |
| `/my/home` 常用应用区（学生/家长，fav 分类） | 同上 | `_build_favorites`（同上引擎） | ✓ 已覆盖（容器 `o_portal_category` 在灰底选择器内） |
| `/my/home` 教师工作台「常用应用」条（faculty/backoffice） | `oe_count` + `oe_count_zero`（有类无样式） | `_build_favorites('faculty')`（周记待批/打卡/校历/私信未读） | ✗ **漏**：容器 `ux-fav-grid` 不在灰底选择器内，0 值实测显品牌蓝底 → **已修** |
| `/my/home` 铃铛角标（学生/家长，迷你头 + hero 两处） | 红底 `oe-mhead-badge` / `oe-hero-bell-badge` | `bell` = 提醒分类未读总和（`_alert_counts` − `edu.alert.read` 水位） | ✗ **漏**：服务端无条件渲染，0 值显红底「0」（JS 轮询后才隐藏） → **已修**（`t-if="bell"`，与 msg_poll.js 0 隐藏语义一致） |
| `/my/home` 提醒折叠头总数 / 提醒卡未读徽标 | `bg-danger` / `oe_count text-bg-primary` | `_alert_counts` − seen_map；raw=0 的卡整卡不渲染 | ✓ 0 值 `t-if` 隐藏 |
| `/my/home` 教师工作台 KPI 徽标（待批周记 / 进行中评估） | `text-bg-warning` / `text-bg-info` | `journal_pending` / `eval_open` | ✗ **漏**：0 值仍显黄/蓝底「0」 → **已修**（`t-if` 隐藏，沿用既有 to-do 角标写法） |
| `/my/home` 教师工作台大卡角标（周记批阅 / 私信） | `badge text-bg-danger` | `journal_pending` / `edu.message` 未读 | ✓ 0 值 `t-if` 隐藏 |
| `/my/messages` 会话行未读徽标 | `msg-conv-unread text-bg-danger` | `edu.message is_read` | ✓ 0 值 `t-if` 隐藏 + 30s 轮询维护 |
| `/my/notice_board/notice` | 行内「未读」徽标；统计盒（通知总数/我的未读等） | `edu.notice.read` 水位 | ✓ 徽标 0 值不渲染；统计盒属 KPI 非角标 |
| `/my/contacts`、`/help/*`、`/downloads`、`/search` 分组计数 | `text-bg-light text-muted` | `len()` | ✓ 恒灰底，无问题 |
| v1 仪表盘 `edu_dashboard`（main.py） | 旧式 `count not in ('',0,None)` 隐藏 | `_dashboard_cards` | 死代码（`EduPortalHomeV2` 叶子类覆盖 `/my/home`），见遗留观察 |

## 2. 修复页列表（修复前 → 修复后）

| # | 漏网点 | 修复前 | 修复后 |
|---|---|---|---|
| 1 | 教师工作台常用应用条 0 角标（`batch2.xml` edu_dashboard_teacher + `portal.css` 选择器缺口） | 0 值有 `oe_count_zero` 类但无样式，实测算得背景 `rgb(14,123,242)` 品牌蓝「0」 | `portal.css` 补 `.ux-fav-grid` 三条角标规则（蓝底/灰底/:has 右留白），实测 0 值变 `rgb(237,238,244)` 灰底、绝对定位与宫格一致 |
| 2 | 学生/家长首页铃铛角标 0 值（`batch2.xml` 两处 `oe-notif-mirror`） | 服务端无条件渲染，0 值红底「0」闪现（禁 JS 常驻） | `t-if="bell"`：0 值不渲染；非 0 显示真实值（stu=13 / parent=8 复测正常） |
| 3 | 教师工作台 KPI「待批周记 N」「进行中评估 N」 | 0 值仍显黄/蓝底「0」 | `t-if` 隐藏（0=无事可办不占位；非 0 照常显示） |

改动文件：
- `custom_addons/edu_portal/views/batch2.xml`（铃铛×2、KPI×2 加 `t-if`，含注释）
- `custom_addons/edu_portal/static/src/css/portal.css`（`.ux-fav-grid` 角标规范 3 条规则）

## 3. 验证记录

- 升级：`docker compose run --rm web odoo -d edu19 -u edu_portal --db_host=db -r odoo -w odoo --stop-after-init` → `Modules loaded.`，EXIT=0，无 ERROR/CRITICAL/Traceback；`docker compose restart web` 后站点 200。
- HTTP 实测（session 登录）：教师/教务 `/my/home` KPI 0 值徽标=空；学生/家长 bell=13/8 正常渲染；`/my/notice_board/notice`、`/my/messages` 200 无 Traceback；`portal.css` 静态资源含 3 条 `.ux-fav-grid` 规则。
- 浏览器实证（Playwright 计算样式）：教师常用区 0 角标 `backgroundColor=rgb(237,238,244)`、`position=absolute`；截图确认学生/教师首页布局无破坏。
- 冒烟回归：`ux_rework_http_smoke` 49/49、`G_messages_smoke` 25/25、`ux_rework_playwright` 32/32，全绿。

## 4. 遗留观察（本批次不修）

1. `edu_portal_templates.xml` 的 `edu_dashboard`（v1 仪表盘模板）与 `main.py` `_dashboard_cards`/`edu_home` 已被 `EduPortalHomeV2` 叶子类覆盖，属死代码，角标仍是旧式隐藏写法——建议后续批次整段删除（本次不动，避免超范围）。
2. ui-reference §6.3 还约定「≥100 显示 `99+`」，当前计数角标未做封顶（如出席率/作业计数随数据增长可能超两位数）——属新显示逻辑，W3 未做。
3. 移动端底部 Tab「消息」无未读红点（msg_poll 仅刷新铃铛/提醒卡/会话行/工作台私信卡）——钉钉式 tab 红点属新功能，W3 未做。
4. 教师工作台大卡「周记批阅/私信」角标用 `text-bg-danger` 计数（非红点），与「红点仅提醒不计数」语义略混用；0 值已隐藏，视觉可接受，未动。
