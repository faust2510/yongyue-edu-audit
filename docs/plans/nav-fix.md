# A9 公开站死链导航接线（nav_fix.py）说明与验证
> **状态**：`归档` ｜ **主题**：`公开站死链导航` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 执行批次：P3（B10 校历完成后的 A9 接线）｜拍板：grill `Q6` A 方案
> 状态：✅ 已结案（2026-08-29）——本地幂等验证通过；生产 edu.example.org 导航核验本就已就绪（0 死链、/alumni/jobs 200），脚本生产 dry-run/实跑均零待办

## 1. 背景

公开站导航（website.menu，站点 1）此前有 8 个 `'#'` 占位死链菜单。
Q6 拍板 A 方案：

| 占位菜单 | 处置 | 目标 |
|---|---|---|
| 活动 / Events | 映射 | `/my/calendar`（一体化校历 B10，登录后使用） |
| 入场 / Admission | 映射 | `/apply`（已有报名真页） |
| 工作机会 / Jobs / 工作 / 校园工作 | 合并 | 「校友与就业」→ `/alumni/jobs`（新公开页） |
| 校友 / Alumni / Alumni Jobs | 合并 | 同上 |
| 论坛 / Forum | 删除 | — |
| 博客 / Blog | 删除 | — |
| 展示位置 / Locations | 删除 | — |

## 2. 脚本

`scripts/nav_fix.py`：独立 python3 脚本（无第三方依赖），通过
`docker exec <容器> psql` 直连目标库，`--dry-run` 预览、实跑单事务提交、
幂等（重复执行零改动）。

### 2.1 名称匹配

- `website_menu.name` 是 jsonb 翻译 dict（`{"en_US":…,"zh_CN":…}`）或纯
  文本，两种形态都解析；中文/英文名均可命中；
- 已指向目标 url 的菜单自动跳过（幂等核心）；
- 只操作 `--website`（默认 1）站点的菜单，不动其他站点。

### 2.2 合并语义

「工作机会/工作/校友」类菜单（含 `Alumni Jobs`、`校园工作`）整棵删除
（子菜单随 `parent_id ON DELETE CASCADE` 一并移除），随后确保恰好一条
「校友与就业」菜单存在——已有则复用并校正 url，不重复创建。新建时：

- 挂在**站点主菜单根**（`website.menu_id` 的子树，本地为「更多」）下并
  按 Odoo 格式补 `parent_path`（`<parent_path><id>/`），否则菜单不会
  进入导航栏渲染；
- 序列取根下现有子菜单最大 sequence + 10（排在下拉末尾，可见）；
- 「校友与就业」的名称/URL 优先于「校友」合并规则判定，二次运行不会
  把自己的目标菜单删掉重建（幂等关键）。

## 3. 用法

本地预览（只读，不改库）：

```bash
python3 scripts/nav_fix.py --dry-run
python3 scripts/nav_fix.py --list          # 列出全部菜单及 A9 分类
```

实跑（本地栈）：

```bash
python3 scripts/nav_fix.py \
    --container edu19-clone-db-1 --db edu19 --website 1
```

生产执行（由于目标无占位菜单则为纯「确保创建」幂等操作）：

```bash
cd /opt/edu-app && python3 scripts/nav_fix.py \
    --container <web容器名> --db edu19 --website 1
```

可选项：`--dbuser`（默认 odoo）、环境变量 `EDU_DB_CONTAINER` /
`EDU_DB_NAME` 兜底（tests/smoke 同款约定）。

> ⚠️ 脚本假定表结构为 Odoo 19 的 `website_menu.name jsonb`、URL 非空；
> 生产库若仍为旧形态（name varchar），先升级 Odoo 再执行。

## 4. 「校友与就业」公开页

- 路由：`/alumni/jobs`（`edu_public`，auth=public，游客可访问）；
- 数据：复用 `/alumni/job/list` 管理列表的来源模型 `edu.alumni.job`
  （Backoffice 发布），公开页只读展示岗位名/薪资/付薪周期/起始/编号，
  按 `招聘中/待定/已结束` 徽标区分，支持 `?state=…` 过滤；
- 模型未安装（edu_portal 缺位）时页面优雅空态，不会 500；
- 模板：`edu_public.edu_alumni_jobs_page`。

## 5. 验证步骤

1. **语法**：`python3 -m compileall -q scripts custom_addons/edu_public`；
   XML 解析 `edu_public/views/*.xml`。
2. **脚本自检**：
   `python3 scripts/nav_fix.py --help`；
   `python3 scripts/nav_fix.py --dry-run`（本地无占位时应只出现
   「新建校友与就业菜单」或「无待办」）。
3. **仿真 8 占位（本地）**：向 `website_menu` 插入 8 条占位菜单
   （活动/入场/工作机会/工作/校友/论坛/博客/展示位置，url=`#`，
   工作机会带一个子菜单），实跑 nav_fix.py，断言：
   - 活动 → `/my/calendar`；入场 → `/apply`；
   - 论坛/博客/展示位置已删除；
   - 工作机会/工作/校友已删除（含子菜单），且存在且仅一条
     「校友与就业」→ `/alumni/jobs`，parent_id=站点主菜单根、
     `parent_path` 形如 `<根路径><id>/`；
   - 首页（匿名 curl /）导航栏出现 `/alumni/jobs` 与「校友与就业」；
   - 再次 `--dry-run` 输出「无待办操作」（幂等）。
4. **公开页**：`odoo -u edu_public --stop-after-init`（或生产
   `-u edu_portal,edu_public` 升级）后重启 web；匿名 `curl /alumni/jobs`
   → 200 且含「校友与就业」；库中造一条 `edu.alumni.job` 后页面可见，
   `?state=recruiting` 过滤正常；造数据清理。
5. **生产门禁核对**（A9 收尾）：上线时先 `--dry-run` 人工确认计划，
   再实跑；`--list` 复核站点 1 已无 `'#'` 占位菜单。

## 6. 变更文件

- `scripts/nav_fix.py`（新）
- `custom_addons/edu_public/controllers/main.py`（新增 `/alumni/jobs`）
- `custom_addons/edu_public/views/edu_public_views.xml`
  （新增 `edu_alumni_jobs_page` 模板）
- `custom_addons/edu_public/__manifest__.py`（版本 19.0.1.0.0 → 19.0.1.1.0）
- `docs/plans/nav-fix.md`（本文）
- 验证脚本：`tmp_t7_nav_test.py`（20 项仿真断言：映射/删除/合并/幂等/
  导航栏渲染/复原）