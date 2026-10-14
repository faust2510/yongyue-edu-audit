# 冒烟测试代理 C：家长端 + 后台教务 + 管理员应用菜单

- 日期：2026-08-23 ｜ 目标：http://localhost:8069（docker edu19-clone，库 edu19，Odoo 19）
- 方法：HTTP 层 python3 requests（`trust_env=False` 直连，绕过系统代理）+ `/web/session/authenticate`；浏览器层 playwright `channel="chrome", headless=True`
- 脚本：`tests/smoke/c_http.py`、`tests/smoke/c_browser.py`
- 截图：`shots/smoke/C_apps_menu.png`、`shots/smoke/C_web_direct.png`、`shots/smoke/C_card_{学生,时间表,讨论}.png`

| 项目 | 方法 | 预期 | 实际 | 结果(PASS/WARN/FAIL) | 证据 |
|---|---|---|---|---|---|
| A1 家长端孩子列表 GET /my/child | HTTP requests (parent@local) | 200 渲染孩子卡片，无 Traceback | 200；「查看仪表盘」卡片（孩子：王小明）；无 Traceback | PASS | len=20433，解析到 `/my/child/5` |
| A2 孩子仪表盘 GET /my/child/5 | HTTP requests | 200 含课表/考勤/作业任一标记 | 200；命中 timetable、考勤、attendance 标记 | PASS | len=24131 |
| A3a 请假表单 GET /my/child/5/leave | HTTP requests | 200 含 csrf 与必填字段 | 200；csrf ✓；字段 leave_type/date_from*/date_to/reason*；action=`/my/child/5/leave/save` | PASS | 表单 HTML 已核对 |
| A3b 请假提交 POST …/leave/save（已造数） | HTTP form post | 成功标志 box=submitted 或「已提交」 | POST→303→`/my/child/5/leave/saved`，**记录已落库**（edu.leave id=15、16，state=request）；但成功页未渲染「已提交」提示框 | WARN | 根因：控制器 redirect 未带 `?saved=1`，模板 `t-if="saved"` 永假（roles.py L353 / roles.xml L313）；手工访问 `?saved=1` 时 alert-success 正常出现。造数理由注明「冒烟测试可删」，日期 2026-08-30~09-01 |
| B4 校友职位管理列表 GET /alumni/job/list | HTTP requests (backoffice@local) | 200 管理列表（表格/卡片，含校友/职位标记） | 200；面包屑「校友工作」+ KPI 卡（My Job Posts=3/Recruiting=2/Pending=1/Closed=0）+ 3 张职位卡（JP006 电气设计工程师、JP004 施工经理、JP002 网络设计师） | PASS | 列表用 `.oe-kpi`+`.o_portal_index_card` 渲染 |
| B5 职位「新建」入口 | HTTP requests | 有新建入口则表单页渲染正常；没有记 WARN | 全页无「新建/新增」入口链接（唯一 href 为列表自身）；路由仅 `/alumni/job/list` 与公开 `/alumni/job/card` | WARN | 无创建表单路由可测 |
| C6 admin 登录落点 | playwright chrome headless | 登录后 URL = /openeducat/apps_menu | `http://localhost:8069/openeducat/apps_menu` | PASS | 等待 7s 后断言 |
| C7 应用卡片数与图标加载 | playwright | 卡片 ≥20 且图标全部真实加载 | 卡片 25 张；图标加载成功 **25/25**（24 张 img naturalWidth>0 + 1 张 FA 兜底 `.o_app_icon_fa`=「安全信息系统」，0 张损坏） | PASS | 截图 shots/smoke/C_apps_menu.png |
| C8 抽样点击 3 张卡进真后台 | playwright（各等 8s） | URL 变为 /odoo/* 且存在 .o_web_client | 学生→`/odoo/student`；时间表→`/odoo/session`；讨论→`/odoo/discuss`；三卡均出现 `.o_web_client` | PASS | 截图 C_card_学生/时间表/讨论.png |
| C9 已登录直接访问 /web（重点回归项） | playwright（等 8s） | 最终落 /openeducat/apps_menu 而非 /odoo/discuss | 最终 URL=`http://localhost:8069/openeducat/apps_menu`，未落 discuss | PASS | 截图 shots/smoke/C_web_direct.png |
| C10 浏览器 console error 收集 | page.on("console") type=error | 空（则 PASS） | 0 条 console error | PASS | 全程监听登录→应用菜单→3 卡→/web 直达 |

## 统计

- 共 11 项：**PASS 9 ｜ WARN 2 ｜ FAIL 0**
- WARN 明细：
  1. **A3b（已造数）**：请假提交链路成功且数据落库（edu.leave id=15、16 state=request），但成功确认提示缺失——`child_leave_save` 重定向缺 `?saved=1` 查询参数，导致模板 `t-if="saved"` 的「请假申请已提交」alert 永不显示（家长提交后看不到任何反馈）。建议修复：redirect 改为 `/my/child/{id}/leave/saved?saved=1`。
  2. **B5**：`/alumni/job/list` 无「新建」入口（亦无对应表单路由），按要求记 WARN。
- 已造数清单（均可删）：edu.leave id=15、16（学生王小明，事假/其他，2026-08-30~08-31 与 2026-09-01~09-02，reason 均含「冒烟测试可删」）。
- 备注：本机系统代理曾致 requests 502，脚本内以 `session.trust_env=False` 直连解决；测试期间容器 edu19-clone-web-1 曾自动重启一次（未人工干预），重启后服务正常。
