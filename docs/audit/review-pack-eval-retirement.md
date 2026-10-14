# 外部评审包：旧评估 A 套（`edu.eval.*`）退役方案

> 用途：把这件事交给**读不到本仓的外部模型**（如 Gemini 网页端）做第二意见。
> 因此本文件**自带全部事实**，不依赖对方能读文件；对方只需要回答文末 §6 的问题。
> 立场声明：§2/§3 是**已核实的事实**（每条带证据位置）；§4/§5 是**约束与已知坑**；§6 是**我的倾向**（欢迎被推翻，但请给判据）。
> 生成日期 2026-10-14 ｜ 生成者：本仓调度 Agent ｜ 对应待办：`docs/plans/README.md` 队列 ④
>
> ⚠ **勘误（2026-10-14，本文件首次提交 `77450c8` 后 1 小时内自查发现并两次更正 —— 都保留了，请连错误一起看）**
> - **第一次错**：初版把「7 条旧路由仍活着且可写」写成了事实。真因：只读了父类 `custom_addons/edu_portal/controllers/evaluation.py`，没检查同目录 `custom_addons/edu_portal/controllers/eval_compat.py` 的**继承覆写**（Odoo 的 leaf 覆盖机制只实例化最底层子类）⇒ 实测三角色 7/7 全是 303。
> - **第二次错**：改口说「根菜单 588 是个空壳磁贴，停掉它即可收尾」并真的改了代码 —— 升级后立刻发现新引擎 `edu_assess` 的 4 条菜单 **parent 就是 588** ⇒ 停用等于关掉新引擎的后台入口。**已当场回滚**，588 恢复 `active=t`。
> - 两次错误同源：**只看定义处，不看生效态**。判据已写进 `docs/code-map.md` §6。

---

## 1. 一句话背景

一个真实的马来西亚华文学校教务系统（单校、单库），跑在 Odoo 19 + OpenEduCat 19 基座上，自研代码全在 `custom_addons/edu_*`（13 个模块），生产域名 `edu.example.org`、库名 `edu19`。评估系统重建过一版新引擎（`edu_assess`），旧的评估功能有**两套**：B 套（独立模块 `edu_eval`）已卸载删除；**A 套（`edu.eval.*`，住在 `edu_portal` 模块里）仍在代码与数据库里，是本次要处理的**。

## 2. 事实：A 套现状（2026-10-14 实测）

| 事实 | 证据 |
|---|---|
| A 套 = 4 个模型：`edu.eval.template` / `edu.eval.template.line` / `edu.eval.task` / `edu.eval.score` | `custom_addons/edu_portal/models/evaluation.py:20 / :47 / :66 / :123` |
| 8 条 ACL（4 模型 × user/system 两组，system 组可写） | `custom_addons/edu_portal/security/ir.model.access.csv:60-67` |
| **7 条旧路由已经全部 303**（→ `/assess` 或 `/assess/my`），**不再可写**。实现在 `custom_addons/edu_portal/controllers/eval_compat.py`（**继承**覆写 `EduEvalPortal`，注册于 `custom_addons/edu_portal/controllers/__init__.py:17`）；父类 `custom_addons/edu_portal/controllers/evaluation.py` 的实现仍在盘上，但**不再被注册**（Odoo 的 leaf 覆盖机制只实例化最底层子类）。2026-10-14 活体实测：教务 / 教师 / 学生三角色 GET 这 7 条路径**全部 303** | `custom_addons/edu_portal/controllers/eval_compat.py:24 / :28 / :32 / :37 / :42 / :47 / :52` |
| 旧子菜单两条已停用：589「模板管理」`active=f`、590「评估任务」`active=f`（本地与生产一致） | 两库 `ir_ui_menu` 直查（id 589/590）；停用机制见 `custom_addons/edu_portal/models/menu_labels.py:44 RETIRE_MENUS` |
| **根菜单 588「综合评估」必须保留**：新引擎 `edu_assess` 的 4 条菜单（793 模板与评分项 / 794 评估任务 / 795 结果与导出 / 796 打分记录）的 `parent` **就是它** ⇒ 删或停用 588 = 连带关掉新引擎的后台入口 | `custom_addons/edu_assess/views/assess_views.xml:261-276`（4 条 menuitem 都写 `parent="edu_portal.menu_edu_eval_root"`）；本地库 `select ... from ir_ui_menu where parent_id=588` |
| 生产 A 套数据：模板 **4** 行、评分项 **13** 行、任务 **1** 行、打分 **0** 行 | 生产库 `edu_eval_template / _template_line / _task / _score` 只读 count |
| 本地 A 套数据：四张表**全 0 行** | 本地库同查 |
| B 套（`edu_eval` 模块）**已卸载**（本地与生产 `ir_module_module.state='uninstalled'`） | 两库直查；删除过程见 `docs/audit/edu-eval-removal.md` |
| 新引擎 `edu_assess` 已上线，A 套代码里**没有**任何东西依赖 `edu_assess`，`edu_assess` 也不 import A 套 | `grep -rn "edu\.eval" custom_addons/edu_assess/` 只命中 `__manifest__.py:22` 的一行**说明文字** |
| 其余引用面：菜单标签覆盖（把旧菜单名标注为「已被 edu_assess 取代」）、两个脚本（`scripts/backup_a_eval_json.py`、`scripts/seed_eval_demo.py`）、以及门禁脚本 `scripts/ui_surface_report.py`（登记路由用） | `grep -rl "edu\.eval" custom_addons/ scripts/` 共 16 个文件（含 `__pycache__`） |

**设计稿里原定的退役五步**（`docs/plans/evaluation-rebuild-design.md` §7.1，原文顺序）：
① 建新引擎（已完成）→ ② 三侧入口 + xlsx 往返真机验收（已完成）→ ③ **旧路由 303 + 旧菜单停用**（已完成：见 §2 第 3/4/5 行）→ ④ 备份（`pg_dump -t edu_eval_* / edu_admin_eval_*` + 4 个模板 xlsx 导出，登记路径）→ ⑤ 删除（B 套 uninstall 已完成 / A 套用 migrations 删表）。
设计稿另有两条硬口径：**「不许先删后建」**、**每步独立 commit、可独立回滚**（§7.1 末尾）。

**当前进度**：①②③ **全部完成**（含根菜单 588 的「有意保留」结论）；B 套已删。**剩余只有 ④ 备份、⑤ 删除**。

## 3. 事实：环境与运维约束（外部建议不得违反）

1. **没有 staging 环境**。本地是 Docker 克隆（`edu19-clone`，库 `edu19`），生产是另一台机器上的同一套 compose；生产库没有可用账号记录在仓里 ⇒ 部署脚本只能做**匿名**验证（登录态路由历来未验证）。
2. **生产数据不可回滚**：没有时间点恢复演练，备份只有 `pg_dump` 落盘（且**从未在生产做过恢复演练**）。
3. **升级是"整批回滚"的**：视图/数据加载失败会让整次升级回滚（真实事故：删掉一个被 xpath 扩展的元素 → `ParseError` 整批回滚，见 `scripts/check_alias_not_extended.py` 文件头）。
4. **基座 `openeducat_erp/` 是官方源码快照，原则上不改**；自研一律在 `custom_addons/edu_*`。
5. **没有自动化测试套件**，验证靠三类：`scripts/check_*.py` 静态门禁（9 张）、活体探针（`tests/smoke/*.py`，跑完自还原）、真机读数（psql 直查）。
6. **删除动作没有"回收站"**：删表 = `DROP TABLE`，删模型 = 删代码 + 升级时 Odoo 自动清理 `ir_model*` 登记。

## 4. 事实：本仓踩过的同类坑（直接影响本次方案）

1. **被 xpath 扩展的视图元素不能直接删**（2026-10-13 事故）：父模板先加载并校验**数据库里尚未升级的子视图** ⇒ 删元素当场 `ParseError` + 整批回滚。正解：元素留成 `t-if="False"` 的壳，子视图改锚别处。
2. **视图继承的 xpath 选择器不得用翻译属性**（`string` / `title` / `aria-label` / `help`…）：Odoo 19 直接 `ParseError: View inheritance may not use attribute 'x' as a selector`（2026-10-14 事故）。
3. **`ir.config_parameter` 改了立刻生效必须直读表**，`get_param` 是 per-worker 缓存（2026-10-14 探针抓到）。
4. **`write()` 后紧跟 `create()` 引用同一唯一键必须显式 `flush_recordset()`**，ORM 的 `create` 不保证先刷出上一条 UPDATE（2026-10-14 探针抓到）。
5. **部署脚本会静默漏模块**（2026-10-14）：rsync 清单是手写死列表，模块不在清单里 ⇒ 「部署通过」但生产上**连目录都没有**；已加硬守卫。
6. **判「某入口是否已退役」不能只看定义处**（2026-10-14，一天内连犯两次）：① 只读父类控制器 ⇒ 漏掉 `eval_compat.py` 的继承覆写（leaf 覆盖只注册最底层子类）；② 只看菜单定义（`views/evaluation.xml:90` 无 action）⇒ 误判成空壳，实际新引擎的 4 条菜单挂在它下面。**判据**：路由要活体实测 + 查有没有子类覆写；菜单要查 `select ... where parent_id=<id> and active`。

## 5. 事实：A 套的数据值不值得留（逐行看过）

生产 4 个模板 / 13 个评分项 / 1 个任务 / **0 条打分**；本地四张表全 0。也就是说：**A 套从未被真正使用过**（没有任何打分数据），只有配置形态的模板与一个空任务。设计稿 §7.2 的结论是「迁移代价算账 → **默认不迁**」，理由是新引擎的模板结构与旧的不同、且没有历史打分需要保真。

## 6. 请外部模型回答的问题（请逐题回答，并给判据；不要重写架构）

**Q1（顺序）**：你同意「④ 备份 → 冻结观察一段时间 → ⑤ 才删代码与表」这个顺序吗？还是认为可以备份完直接删？我的倾向：**保留 2 周冻结窗口**（观察有没有人报"找不到评估"），因为生产没有 staging、且删除不可逆。

**Q2（数据）**：那 18 条真实数据（4 模板 + 13 评分项 + 1 空任务 + 0 打分）你建议迁进新引擎、还是只留备份（`pg_dump` + JSON + xlsx）？我的倾向：**不迁**，只留三份备份并在台账登记路径。请指出"不迁"的风险点（例如学校某天要查旧模板长什么样）。

**Q3（删除方式）**：A 套住在 `edu_portal` 里（不能卸模块），所以删除 = 删 4 个模型类 + 8 条 ACL + 7 条路由（含 `eval_compat.py` 这个 303 层）+ 视图/菜单 data + 用**幂等 migration 脚本 `DROP TABLE`**。你认同这个拆法吗？有没有更安全的替代（例如"模型留着、只清空数据 + 菜单停用"长期不删）？我的倾向：**删，但 migration 必须先校验备份存在**。

**Q4（易误删清单）**：第 ⑤ 步最容易出人命的地方是「看起来该删、其实是新引擎容器」的东西 —— 我自己就误判过一次（见文首勘误第二次）。除了菜单（`edu_assess` 的 4 条挂在旧根菜单 588 下），**还有哪些类别**需要先查引用再删？请给**可执行的判据清单**。我的倾向：删任何菜单/动作/视图前，先查 ① 活子菜单 ② `ir_model_data` 引用 ③ 被 xpath 继承（`inherit_id` 反查）。

**Q5（检查清单）**：删表/删模型时，除了代码里的显式引用，还有哪些**隐式耦合**可能炸？请给**检查清单**（要能在 psql / grep 里执行的判据），例如：`ir_model_data` 残留、`ir_model_fields`/`ir_model` 登记、`ir_ui_view`/`ir_act_window`/`ir_ui_menu` 的绑定、`ir_model_access`、`ir_rule`、`mail.followers` / `ir_attachment` / `ir_cron` / `ir_filters` / `ir_exports` 里对模型名的字符串引用、审计日志里的字符串、以及"外键指向被删表"的第三方表。我的倾向：**按模型名全库扫一遍字符串 + 逐表列外键**，而不是凭记忆。

**请不要回答**：换技术栈/微服务/重写；"应该补测试"这类没有落点的建议；假设有 staging 或 CI；建议上 Odoo 企业版。
