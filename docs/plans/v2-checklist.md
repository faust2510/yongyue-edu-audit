# v2 改造总清单（2026-08-24 拷问会议定稿 · 共识版）
> **状态**：`已上线` ｜ **主题**：`v2 改造清单` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「待用户最终确认后动工」，实际已于 `ebc5cff` 提交（2026-09-26 核对发现）。正文未改动。

> 状态：待用户最终确认后动工 ｜ 来源：/grill-me 拷问会议（Q1-Q7 已逐题拍板）

## A 类 · 缺陷修复

| # | 项 | 说明 |
|---|---|---|
| A1 | 登录 Session expired (invalid CSRF token) | 复现定位（疑似闲置过期+旧表单提交），修复+友好提示 |
| A2 | 通知角标永不减少 | 并入 B5 未读引擎 |
| A3 | OMR/光学考试死菜单 | ✅ 已拍板：代码级**删除**（路由+模板+卡片全清），非隐藏；见 batch2/batch3 |
| A4 | 仪表盘原公司残留（销售产品等） | 全面清扫非学坊卡片 |
| A5 | 学生搜索不含作业 | 扩至作业/课程/公告/账单 |
| A6 | 快速操作 & 自研应用图标语义化 | 在线课程🎓、日常管理📅 等，替换 windows 风默认图 |
| A7 | 进应用后找不回面板 | 后台持久面包屑 + 返回应用面板固定入口 |

## B 类 · 已拍板决策

| # | 决策 | 要点 |
|---|---|---|
| B1 | 评估中心 Odoo 自研 | PRD=行政文档《方案-老师端评估中心》：三大评估(freshman/student/intern)、Excel式可编辑打分表、雷达图、可新建评分表、模板/权重/等级线(60及格90优秀)、管理员集成面板(学生+教职) |
| B2 | GitHub 幻觉化 方案B | 品牌参数化；推送前幻觉脚本：Sample Seminary/edu.example.org/office@edu.example.org；抹真实 IP(edu.example.org/203.0.113.10)/域名/邮箱；生产真身零感知 |
| B3 | 三语 i18n | ✅ 已完成：zh_TW/en_US 官方包激活加载、切换器 UI（登录页+门户）、语言偏好持久化路由 /my/lang/<code>。**遗留（待拍板范围）**：自研模板字符串翻译键化重构——手写 PO 方案实测导致注册表崩溃，需改用标准导出流程（odoo -u 时自动抽取）后按词条补翻；选项 A 接受现状 / B 高频页先行 / C 全量 \|；**已完成过渡方案**：高频页（登录身份标签/首页卡片标题/分组名）已中英双语标注并部署生产 |
| B4 | ✅ 已上线 | 演示登录按钮→身份标签（仅填用户名、密码零暴露、浏览器原生记忆）；生产明文账密事故已清零（batch3.xml+quick_login.js） |
| B5 | 通知已读引擎 | 公告可点击→阅后即记(user×notice 读表)→未读角标精确递减→一键全读→通用机制复用 |
| B6 | 打卡 C 全要+学生月历 | 管理员班级×周热力板+未打卡名单催办；学生火焰连击卡+三状态大按钮+个人打卡月历(出勤/灵修/读经三轨)；站内漏卡横幅；TG 催办二期 |
| B7 | 新手引导 A+C | 角色上手清单卡(真实行为自动打勾)+图文帮助中心；交互高亮导览暂不做 |

## 执行顺序

```
P0 稳定   → A1 CSRF
P1 高频   → B5 → A6/A7 → A3/A4/A5
P2 大功能 → B1 评估中心（动工前先交详细设计稿给用户过目）
P3 体验   → B6 → B3 → B2 → B7
```

每批：本地验证 → 推 GitHub(B2 上线前手动脱敏) → rsync 部署 edu.example.org → 截图回报。

## 部署与环境速查

- 生产：edu.example.org = prod-host(203.0.113.10) /opt/edu-app，compose edu19-prod，
  nginx sites-enabled/edu-strcs → 127.0.0.1:8069(+8072 websocket)，CF 橙云
- 容器 uid：odoo=100 / postgres=999（宿主目录属主必须匹配，PGDATA 700）
- 回滚：/root/backup-edu-system-*.tgz + systemctl enable --now edu-system.service
  （详见 docs/deploy-malaysia.md）
- 本地开发库参数 demo_login_enabled=True（演示按钮仅本地可见）

> v2.1 部署纪律（B9/B10 起）：每批必须含 `-u edu_portal`（创建 edu.message/
> edu.event 表；代码先行未升级会致 /my/home 500）→ 探活审计（A8 Runbook §4）→
> 数据清理一律 DELETE/TRUNCATE，禁止 DROP TABLE（详见 docs/deploy-a8-runbook.md §5.1）。

---

# v2.1 改造总清单（拷问/brainstorming 追加轮定稿 · 共识版）

> 来源：grill-me 拷问会议 Q1.5/Q2/Q2.1/Q3/Q4/Q5 + brainstorming Q6 逐题拍板。
> 状态：计划文档已更新，待用户最终确认后按批动工。

## A 类 · 缺陷修复（v2.1 新增）

| # | 项 | 说明 |
|---|---|---|
| A8 | 生产库「陈年视图」修复 | 日常管理（任务/活动/媒体/互动）与综合评估入口报 missing required fields / 访问错误=**生产模块未升级**（代码已改，库中动作/视图过期）。修复：`-u edu_portal,edu_eval,edu_life,edu_schedule,edu_apply` 后重启；**部署流程新增「菜单动作探活审计」脚本**（全部根菜单×动作×res_model 有效性一键校验，复用 tests/smoke/F_roles_smoke.md t12 思路），上线前必跑。✅ 已工具化（t3）：`scripts/check_prod_menus.py`（全菜单审计：动作/模型/视图挂载/组缺失）+ 升级 Runbook `docs/deploy-a8-runbook.md` |
| A9 | 公开站死链导航处理 | 8 个 '#' 占位（Q6 拍板 A 方案）：活动→并入校历页；入场→改链 `/apply`（已有真页）；工作机会/工作/校友→合并新建「校友与就业」公开页（复用 /alumni/job/list 数据）；论坛/博客/展示位置→**删除** |
| A10 | 样品账号与演示数据清理 | 上线前 P0 门禁：列出全部样品账号邮箱清单 → 一键停用/删除；清理种子脚本（seed_*）生成的演示班级/课程/打卡/评估等数据。用户已确认正式使用前样品账号全部删除。✅ 已工具化（t3）：`scripts/cleanup_demo_data.py`（--dry-run 预览/--execute 执行，账号默认停用，逐表 savepoint 删除，CRS-*/PRP-2026 真实骨架排除在外） |

## B 类 · 已拍板决策（v2.1 新增）

| # | 决策 | 要点 |
|---|---|---|
| B8 | 通讯录 + 邀请码绑身份 | 门户「通讯录」页（我的主页卡片入口）：按 老师/学生/家长 三组自动归类，可见性=熟人圈（家长→自己孩子的任课教师+管理员；学生→自己的教师+管理员；教师→本班学生/家长+管理员；管理员→全部）。`edu.invite.code` 增加身份(学生/家长/教师)+对应人 m2o，注册成功自动挂接 user_id；附「老账号补挂身份」后台小工具（历史账号一人一挂） |
| B9 | 轻量双向私信 | 新表 `edu.message`（发件人/收件人/正文/时间/已读），我的主页未读角标并入 B5 通知引擎，30s 轮询；不做群聊/附件、不走 Discuss。收发权限=熟人圈（同 B8 可见性），教师↔教师第一版不开放 |
| B10 | 一体化校历 | 门户「校历」页（月视图）聚合：本学期课程(op.session)+考试(op.exam)+停课日(edu.schedule.holiday)+新轻量活动模型 `edu.event`（标题/起止/地点/限定班级）；按角色过滤；新建活动自动冲突检测（同教师/教室/班级时段重叠→红字拦截，规则对齐排课冲突拦截）。不做拖拽/循环事件 |
| B11 | UI 工作台美化 | 对标钉钉/企业微信「家校工作台」：顶栏+左侧角色导航（移动端底部 Tab）+首页工作台宫格+蓝绿色系+大字号+圆角卡片+分组标题。**铁律：只美化，零功能丢失**——每页改造后对照路由清单逐一验证功能可达可操作，截图对比；参考式开发（学规范不搬代码） |
| B12 | 仓库↔生产对账 | 一次性导出生产「已安装模块清单」（设置→技术→模块，或 sql 查 ir_module_module）与仓库对比，消弭企业版残留与未知模块，避免以后再出现「库里无码」入口 |

## 执行顺序（v2.1）

```
P0 生产稳定 → A8（升级+探活审计）｜上门禁确认：A10 样品清理
P1 通讯录   → B8（含邀请码绑身份、老账号补挂工具）
P2 私信     → B9（依赖 P1 可见性）
P3 校历     → B10 + A9（活动并入校历；入场/校友接线；删论坛博客）
P4 UI 美化  → B11（零功能丢失回归：全程对照路由清单）
P5 收尾     → B12 对账、A10 复查、全量回归
```

每批：本地验证 → 推 GitHub（沿用 B2 脱敏纪律）→ rsync → `-u` 升级 → 探活审计 → 截图回报。

## v2.1 备忘

- 综合评估改名已完成（代码）：后台菜单「评估中心」→「综合评估」，门户标题/新手引导同步，路由 `/my/evaluation` 不变；生产需随 A8 升级生效。
- 权重(倍率)文案已改：模型 help + 门户表头 + 口径说明（edu_eval）。
- P0 工具（t3）：A8 探活审计 `scripts/check_prod_menus.py`；A10 样品/演示清理 `scripts/cleanup_demo_data.py`（默认 --dry-run）；批次上线流程见 `docs/deploy-a8-runbook.md`（rsync→chmod→-u 五模块→restart→探活→A10 门禁）。
- 生产升级命令：
  `docker compose exec web odoo -d edu19 -u edu_portal,edu_eval,edu_life,edu_schedule,edu_apply --stop-after-init` 后 restart web。
## v2.2 头像与品牌化批（已上线 2026-08-28）
- 头像自助更换：b11 顶栏点自己头像 / 用户菜单「修改头像」→ 弹窗上传
  （edu_portal/controllers/avatar.py，POST /my/avatar/upload，只写本人 partner）。
- 登录页去 Odoo 化：website.login_layout 挂 yy-login-page（edu_brand/views/login.xml），
  蓝白渐变 + 白卡片；去掉「登录 Odoo.com」（auth_oauth_provider id=1 enabled=false）、
  「Powered by Odoo」、DB 管理链接；登录页身份快捷按钮改为
  ir.config_parameter edu.dev_quick_login=1 才渲染（生产不设，已关）。
- 应用面板统一品牌蓝 FA 瓦片（roles.py _APPS_FA_BY_NAME 按菜单名映射，
  roles.xml 套 b11 骨架；不再显示彩色 OpenEduCat web_icon/旧梅紫 o_app_icon_fa）。
- partner 字段中文标签上线（院系/年级/学制 + 「即本科、硕士等」说明）。

## v2.3 拷问批（2026-08-28 已上线）
- 删「排课管理」应用壳（菜单 571 及周课表/重复子项）；排课查看统一走校历 /my/calendar
  （侧栏/落地页/帮助文本/快捷操作全部改指）；后台维护与创建工具保留在官方
  「时间表」应用（周期排课/整周复制/停课管理 parent=341，教室/时段/全部课时复用中文视图）。
- 全站梅紫清零：enterprise.css/portal.css/custom_home.css/batch3.css 全部 #714B67 色系
  → 品牌蓝；bootstrap 派生控件（dropdown active/btn-light）在 #wrapwrap.o_portal 下统一蓝；
  im_livechat_channel 聊天窗配色改 #0E7BF2（两个频道）。
- 入口合并：学术日历卡、使用指南卡、即时聊天卡隐藏（私信=唯一消息入口）；
  灵修日记改名「我的周记」；「我的课表」落地入口改名「校历与课表」。

## v2.4 官方后台去紫（2026-08-28 已上线）
- 根因：Odoo 官方默认 `$o-community-color:#71639E` / `$o-enterprise-color:#714B67`（社区版主色即紫）；
  整个官方后台 webclient（导航栏/按钮/控件面板/状态条/列表）默认紫。
- 修复（edu_brand）：
  1) backend_variables.scss 用**普通赋值**覆盖官方基础变量（不能用 !default）+ 重做
     $o-btns-bs-override 快照 map（primary 按钮蓝）；
  2) backend_b11.css 硬覆盖残余（导航栏/次要按钮激活态/状态条/必填框/表格选中/编辑器单元格）；
  3) 用户截图中 71% 面积紫的顶部条 → 实测三视图（应用网格/课时列表/排课日历）严格紫 0.000%，
     导航条 rgb(14,123,242)。
- 教训：Odoo 老主题/官方 UI 的“紫”来自 primary_variables.scss 的变量与 map 快照，
  改 CSS 文件级覆盖（backend_b11.css）最可靠；SCSS 变量需连带快照 map 一起覆盖。
