# 永约学坊教务系统（Odoo 19 + OpenEduCat）

永约学坊（Covenant Reformed Seminary）的完整教务系统：以 **Odoo 19 + OpenEduCat 19.0 社区版快照**为基座，自研 `custom_addons/edu_*` **14 个模块**（v3 新增 `edu_zh` 汉化/术语覆盖）实现四角色门户、官网、报名、灵命生活、行政评估、排课工具、在线测验、Telegram 推送、资料下载中心与**一条龙学习中心**。生产部署于马来西亚 prod-host（203.0.113.10，`/opt/edu-app`，经 Cloudflare 绑定 edu.example.org）。

> AI 助手先读 [docs/code-map.md](docs/code-map.md)（一页代码图谱）；实现铁律见 [docs/dev-workflow.md](docs/dev-workflow.md)。

## v3 改造（2026-09-12）

已交付：**去 Odoo 痕迹**（用户可见面 0 命中：52 静态路由 + 动态发现 + 邮件面 4/4 + 数据不变量 0 违规）、
**学坊本土化**（「学费→统筹费」全站可见面 0 残留；币种 CNY；新增 `edu_zh` 词条覆盖模块）、
**一条龙服务**（`/my/study` 课程中心：课节级会议链接 + 课前提醒 + 课程资料 + 成绩三层 + 出勤；
`/my/home` 工作台使首页从 3744px 降到 1366–1469px）、**重复劳动自动化**（批量审批/成绩批量与留痕/公告模板与定时/考勤补录/自助证明）。

- 交付报告（含目标对照、缺陷台账、分层验收、已知限制、生产部署前置与回退）：[docs/plans/ux-v3-delivery.md](docs/plans/ux-v3-delivery.md)
- 独立验证报告（七项 + 各轮复评）：[docs/plans/ux-v3-verification.md](docs/plans/ux-v3-verification.md)
- 门禁规范与工具说明：[tests/smoke/UX_V3_GATE.md](tests/smoke/UX_V3_GATE.md)
- 调研档案（先调研后设计）：[docs/research/](docs/research/)

**改动闭环（六步闸门）见 [docs/dev-workflow.md](docs/dev-workflow.md)**；升级一律走 `scripts/safe_upgrade.sh`
（串行锁 + 正确 DB 参数 + `--no-http` + 挂载自检 + **升级前离线静态检查** + 时间戳日志保留 10 份）。

## 快速开始

```bash
# 1. 起站（PG16 + Odoo19，项目名 edu19-clone，DB edu19，端口 8069/8072）
docker compose up -d

# 2. 改码后升级模块（必须 EXIT=0 无 Traceback）
#    用安全脚本：串行锁 + DB 参数 + --no-http + 挂载自检（默认 -u；仅首装新模块用 -i，
#    因 -i 对已装模块不重载 data/view 文件，会给出「升级成功但页面没变」的假象）
bash scripts/safe_upgrade.sh edu_portal

# 3. 验收（先离线自证，再探活，最后真跑）
python3 scripts/check_english.py --selftest && python3 scripts/check_odoo_trace.py --selftest \
    && python3 scripts/check_view_xpath.py --selftest && python3 tests/smoke/gate_seam_check.py   # 【0】离线自证族
python3 scripts/check_english.py               # 英文/品牌门禁（口径：must-fix = 0 且 brand = 0）
python3 scripts/check_odoo_trace.py            # 去 Odoo 痕迹（页面/属性/邮件/数据不变量 四维 0 命中）
python3 tests/smoke/ux_v3_route_matrix.py      # 100 路由 × 5 角色（PASS/WARN/PENDING/FAIL/ENV 分流）
python3 tests/smoke/zero_loss_reachability.py  # 旧首页 35 卡零丢失 + 共享类契约
python3 tests/smoke/audit_completeness_smoke.py # 成绩留痕完整性（后台直写 + 门户三路径）
python3 tests/smoke/data_driven_brand_leak.py  # 数据驱动品牌泄漏
python3 tests/smoke/downloads_v2_smoke.py      # 幂等冒烟（44 项）
python3 tests/smoke/notice_privilege_smoke.py  # 特权冒烟（15 项）

# 4. 部署生产（rsync 常变模块 + 远端 -u + 起站 + 冒烟）
bash scripts/deploy_myedu.sh edu_portal,edu_brand
```

## 模块地图

| 模块 | 职责 |
|---|---|
| `edu_portal` | 四角色门户中枢：首页卡片引擎、学生/教师/教务/家长全部路由、资料下载中心 v2.1（单页两态：下载 + 教务管理模式）、后台审批、帮助中心、改密、邀请码注册 |
| `edu_brand` | 品牌官网（首页/院系/校刊/报名引导/登录页）+ **去 Odoo 品牌化**（校徽 favicon/公司 logo、Powered by 替换、用户菜单外链移除、`/login`/`/apps` 友好别名、数据侧技术账号显示名治根） |
| `edu_zh` | **汉化与术语覆盖（v3 新增）**：PO 覆盖基座机翻硬伤 + 15 条 JS/code 词条（`translatedTermsGlobal` 兜底，无需 JS patch）；「学费→统筹费」、USD→CNY、混排品牌串（core tooltip）汉化 |
| `edu_public` | 公开功能页：校友与就业 /alumni/jobs、校园招聘、数字图书馆等 |
| `edu_apply` | 报名入学：元数据驱动报名表（管理员可视化配字段/必填，锁定核心字段） |
| `edu_life` | 灵命生活：读经/灵修打卡月历、周记本与教师批阅、打卡统计 |
| ~~`edu_eval`~~ | ~~行政评估~~ **2026-09-29 已卸载并删除模块**（用户授权；三表 0 行、无真实数据，证据 `docs/audit/edu-eval-removal.md`）。评估现由 `edu_assess`（`edu.assess.*`，门户 `/assess`）承担 |
| `edu_schedule` | 排课工具：周期排课三步流、整周复制、停课日、冲突检测 |
| `edu_quiz` | 在线测验：后台出题 → 学生作答 → 自动判分 |
| `edu_telegram` | Telegram 绑定/推送/教师点名录分门户 |
| `openeducat_erp/` | OpenEduCat 官方 19.0 快照（14 模块基座，**只读不改**，扩展一律进 edu_*） |

## 角色与权限

| 角色 | 账号（本地） | 落地页 |
|---|---|---|
| 管理员/教务处 | admin、backoffice@local | Odoo 后台；门禁型管理页（公告发布/请假审批/申诉处理/资料管理）凭 `roles.privileged_staff()` 在门户直管 |
| 教师 | faculty@local | Odoo 后台 + 门户教师页（批阅/统计/发布） |
| 学生/家长 | 邀请码注册（/web/register） | /my/home 门户 |

> 生产已删演示账号，仅留管理员与教务账号；本地演示数据（stu@local 等）由 `scripts/seed_*.py` 幂等重建，演示内容必须带【演示】标记。

## 关键约定（详见 dev-workflow.md 与 code-map.md §6）

1. Odoo19 语法：`group_ids`（非 groups_id）、`<list>`（非 tree）、新表达式 invisible；`sudo()` 只在 recordset 上
2. 权限：复用官方组不建新组；ACL 进各模块 `security/ir.model.access.csv`；写路径控制器 `sudo()` + 归属校验 + POST+csrf
3. 门户页外壳 `t-call="edu_portal.edu_page"`；写操作走兄弟路由 `/xxx/save`；QWeb 内禁 `%` 格式化（控制器预格式化）
4. 品牌红线：联系方式仅 scrtsschool@gmail.com；假资料一律清除；种子幂等
5. 品牌资产（favicon/logo/落款）在 `edu_brand/data_brand/`，官方 xml_id 带 noupdate——已装库改品牌需一次性 ORM 写入

## 文档索引

- [docs/code-map.md](docs/code-map.md)：模块/路由/模型/脚本一页图谱（改架构必须同步）
- [docs/dev-workflow.md](docs/dev-workflow.md)：**六步闸门** + 实现铁律（**功能队列已迁至 [docs/plans/README.md](docs/plans/README.md#待办队列)**）
- [docs/plans/README.md](docs/plans/README.md)：**计划文档总索引**（逐份登记：主题/状态/取代/要点/判定依据 + 待办队列 + 同一主题读哪份；份数以该索引顶部标注为准）
- [tests/smoke/](tests/smoke/)：幂等冒烟脚本（requests 需 trust_env=False，脚本已内置）
- 生产运维：`docs/deploy-malaysia.md`；合规自查：`docs/compliance-audit.md`

## 历史沿革（2026-08）

8/22 复刻起步（探测技术栈→本地装同款→抓原站 32 页→edu_portal 26 路由复刻）→ 8/22-23 死链清零、邀请码注册、行政系统（打卡/积分）、教师端菜单裁剪 → 8/24-25 自研风暴：edu_life/edu_eval/edu_schedule/元数据报名表 + 夜间 UX 优化 + 帮助中心/改密/教师工作台 → 8/28 资料下载中心 → 8/29 下载中心 v2.1（单页两态+批量操作+审计）、管理员特权放行、全面去 Odoo 品牌化、A9 导航结案。逐日细节见 git log 与 docs/plans/。
