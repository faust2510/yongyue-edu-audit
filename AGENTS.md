# AGENTS.md — 给自动化编码代理（Jules / Gemini CLI / Codex / Cursor …）的入职说明

> **真相来源**：`CLAUDE.md`（铁律）、`docs/code-map.md`（一页代码图谱）、`docs/dev-workflow.md`（六步闸门）。
> 本文件是它们的**精简版**，供代理在无人工值守时快速定位规矩；**冲突时以上述三份为准**。
> 改了本文件里的铁律条目，必须同步 `CLAUDE.md`，否则算文档漂移。

## 1. 这是什么项目

永约学坊（神学院）教务系统：**Odoo 19 + OpenEduCat 19.0 社区快照**为基座，自研代码全部在 `custom_addons/edu_*`（**15 个模块**），
四类角色（学生 / 家长 / 教师 / 教务处·管理员）的中文门户，简繁英三语。
`openeducat_erp/` 是官方源码快照，**不进本仓**（见 `.gitignore`）；基座能力一律在 `custom_addons/` 里继承/扩展。

## 2. 动手前按顺序读

1. `docs/code-map.md` —— 模块 / 路由 / 模型 / 脚本 / 硬约定（§6）
2. `docs/dev-workflow.md` —— 六步闸门与实现铁律
3. `docs/plans/README.md` —— **待办队列的唯一来源**（75 份计划索引）
4. `docs/audit/README.md` —— 已有审计结论（**读它，别重复审一遍**）

## 3. 环境实话：你很可能没有 Docker

完整闭环需要 Docker + Odoo 19 + PG16（`bash scripts/safe_upgrade.sh <模块>`、`docker compose`、真站冒烟）。
云端 VM 通常没有 ⇒ **不要尝试这 41 个依赖 docker 的脚本**：它们失败不代表你改错了，只代表环境不在。
**你能跑、也必须跑的，是下面这组离线门禁。**

## 4. 必须保持全绿的离线门禁（2026-10-14 本机实测基线）

```bash
python3 scripts/check_english.py --selftest      # 48 断言
python3 scripts/check_english.py                 # 汉化/品牌门禁（must-fix 必须为 0）
python3 scripts/check_odoo_trace.py --selftest   # 53 断言
python3 scripts/check_view_xpath.py --selftest   # 26 断言（需 lxml）
python3 scripts/check_view_xpath.py
python3 tests/smoke/gate_seam_check.py           # 两个门禁的接缝（六样本）
python3 scripts/check_docs_index.py              # docs/plans 索引与状态行逐字一致
python3 scripts/check_manifest_order.py
python3 scripts/check_manifest_tracking.py
python3 scripts/check_qweb_dict_foreach.py
python3 scripts/check_recordset_none.py
python3 scripts/check_shell_exitcode.py
python3 scripts/check_ui_surface.py
python3 scripts/check_po_sanity.py
python3 scripts/check_alias_not_extended.py
python3 scripts/check_nav_reachable.py           # 依赖 tests/audit/audit_lib.py
```

**已知红的（不是环境问题，是真缺陷，欢迎修）**：
`scripts/check_doc_module_count.py`（`docs/code-map.md:47` 写 14，实测 15）、
`scripts/check_md_tables.py`、`scripts/check_menu_data_sync.py`（菜单 547 通道漂移）、
`scripts/check_nav_jobs_entries.py`（导航 2 条指向空页 `/jobs`）。

**跑不了、别跑的**：`check_accessibility.py`、`check_inpage_links.py`、`check_ui_usability.py`（playwright）、
`check_view_selector_attrs.py`（需 odoo 运行时）、`check_live_registry.py`、`check_prod_menus.py`、`check_odoo_trace.py`（全模式）、
`check_asset_freshness.py`（比的是文件 mtime 与正在跑的容器，新检出必然 STALE）。

## 5. 铁律（违反会返工）

0. **先调研，后设计**：Odoo 19 核心源码 → OCA → Moodle/Canvas → 国内同类；**能装不写、能抄不造**；结论落 `docs/research/<主题>.md` 并带一手来源 URL，未核实的标「未验证」。
1. **Odoo 19 语法**：字段 `group_ids`（不是 `groups_id`）、视图 `<list>`（不是 `tree`）、SQL 约束用 `models.Constraint`；`sudo()` 只作用于 recordset。
2. **权限**：不建自定义组；控制器用 `current_student()/current_faculty()/privileged_staff()` 判定；写操作一律 `POST + csrf`，兄弟路由 `/xxx/save`；越权一律按「不存在」处理。
3. **品牌红线**：旧学院假资料必须清除；联系方式只允许永约学坊真实资料；演示数据带【演示】标记、测试数据带【冒烟】标记。
4. **QWeb 模板内禁止 `%` 格式化**（装载期 `%%` 折叠会崩）；数字/日期在 Python 侧预格式化后传入。
5. **汉化门禁**：改动用户可见文案后必须跑 `python3 scripts/check_english.py`，可见英文串必须为 0。
6. **验证闭环**：改码 → `bash scripts/safe_upgrade.sh <模块>`（默认 `-u`；`-i` 只用于首装新模块）→ EXIT=0 无 Traceback → 各角色冒烟 → `check_english` → **路径范围** git commit。
7. **生产**：本仓不含生产凭据；**任何部署命令都不要跑**。
8. **数据结构变更**：`init()` 迁移必须 savepoint + `information_schema` 列检查（裸 `except` 会毒化升级事务）。
9. **多窗口协作**：小步路径范围提交；禁全树 `stash`/`reset`；同容器升级串行（`scripts/safe_upgrade.sh` 内含串行锁）。

## 6. 禁区

- `openeducat_erp/` 只读：**不在里面改任何文件**，要改就在 `custom_addons/` 里 `_inherit`。
- **不许为了让门禁变绿而改门禁本身**（`scripts/check_*.py` 的判定口径、白名单、阈值）；不许删 `docs/audit/` 与 `docs/plans/` 的历史结论。
- 不新增第三方依赖、不改 `docker-compose.yml`、不动 `config/`。
- 不提交任何真实师生数据或生产主机信息。
- `docs/plans/` 新增文档必须同时登记进 `docs/plans/README.md` 索引并写状态行，否则 `check_docs_index.py` 报红。

## 7. PR 规矩

- **一次只动一个模块或一个主题**；标题 `[<模块>] <一句话>`。
- PR 描述里贴出你实际跑过的门禁命令与输出尾部（证明基线）。
- 不做大范围格式化/重排、不碰无关文件；diff 越小越好。
- 修不了的写进报告，**不要瞎改**。
