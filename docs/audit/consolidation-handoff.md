# 交接：功能重叠收口（edu-consolidation）—— 已完成什么、停在第几格、怎么接着做

> 写于 2026-09-17 傍晚（会话被删除前）。背景：永约教务系统（Odoo19 + OpenEduCat 改造；本地栈 docker 项目 `edu19-clone` / 库 `edu19`）经多波次并行开发出现重复实现，本轮做"收口"。
> 团队已结束并归档，任务与信箱在 `.agent-teams/archive/edu-consolidation/`。

## 一、已完成并落库（commit / 文档都在仓里）

| 任务 | commit | 结果 |
|---|---|---|
| t1 审计固化 | `dd0074f` | `docs/audit/feature-overlap-audit.md`：8 类重叠四层证据 + 40 根菜单施工图。**两处纠错**：根菜单实测 40（非 47）；"考勤四套重复"实为 `op.attendance` 一模型两条录入通道 |
| t2 菜单收口 | `682d3a1` | 教务 31→**12**、admin 38→**14**、教师 19→**9**；全库菜单 **605→605 零删除**；档2 混档（121/142/196/566 整棵停用，1/15 根+子树挂 `base.group_system`）；容器仅 `300 += [87]`；工具 `scripts/consolidate_menus.sh` / `gen_menu_data.py` / `rollback_menus.py`；模块 `custom_addons/edu_nav` |
| t5 打卡两套合一 | `7e67a0a` | 7 条旧行并入 `edu.checkin.record`（新建 8＝到堂7+读经1、note 回填 4、删除 0）；旧表 7→7 只停写；`/my/checkin*` → 303 `/my/checkins*`；新增类型「到堂打卡」 |
| t6 防复发 | — | `docs/dev-workflow.md` 第 0 步「落地前查重」+ `docs/audit/deprecated-inventory.md`（C1–C7 删除门槛；唯一可进入删除评估的是 `edu.daily.checkin`） |
| t9 断言改强 | `5bbb977` | 全量冒烟 **15/15 PASS**；矩阵 495/0；旧入口强断言（`allow_redirects=False` + Location 精确） |
| t10 导航收口 | `b2d974c` | 删 3 个指向空页 `/jobs` 的入口、188 改指 `/campus/jobs`、校友岗位页中文化 |
| t11 升级重放止血 | `52c2c8b` | 受影响菜单 xmlid 置 `noupdate=1`（357 声明 / 419 受保护 / 46 模块）；工具 `scripts/consolidation_persist.py` |
| t12 演示播种确定性化 | `ae0087a` | `edu_life` 一次性开关（`ir.config_parameter edu_life.demo_checkin_seed`，按 student_id）+ 固定绝对窗口（上一个完整 ISO 周）+ 兜底整段跳过 |

## 二、没做完（停止时的状态）

1. **t13 到堂类型固化为 `edu_life` 模块 data** —— **进行中**：工作区有未提交改动 `custom_addons/edu_life/data/demo_life.xml`、`models/checkin_type.py`。
   要求：按 name 幂等 get-or-create（复用现有 id=5，老库不造重复）、新库/重装自带；顺手把 `demo_life.xml` 里"方法内部幂等"那句注释改准。
2. **t14 修 F6「台账就地覆写」** —— `--apply` 每次重写 `latest.jsonl` ⇒ 同名文件不同时点破坏性不同（含 `created` 时 rollback 会真删）。
   改法：每次 apply 落**时间戳新账** + `latest` 仅作指向 + `rollback` 前**先复制并校验是否含 created**（不含则拒绝真删）+ 台账显式记录"输入版本/模式/是否含 created"。
3. **t15 修 F7「原生重建 `/jobs` 入口」** —— 业主是 menu **206**（持 xmlid `website_hr_recruitment.website_menu_jobs`），205 是孤儿。
   修法：在 `edu_nav` 按该 xmlid 覆盖 `is_visible=false`（**首选，不删记录**）+ 对同 xmlid `noupdate=1`；**验收核心**：再 `-u website_hr_recruitment` 一次仍不显示。退路（删记录 + 墓碑保护）**必须先实测** xmlid 尚存但记录已删时 `_load_records` 的行为，不许按推断写进方案。
4. **t7 终验 / t8 终审** —— 验证方判据已备（`--status → 未受保护=0` 前置闸门、`--batch` 默认、`--restore` 按需、零 `-u` 静态取证法见 `docs/audit/t11-persistence-evidence.md` §7.3）；auditor 的终审未跑。
   相关报告：`docs/audit/consolidation-verification.md`（含 §11 修订记录）、`docs/audit/finding-F1…F7`、`docs/audit/menu-nav-handoff.md`。

## 三、必须一起带走的口径与纪律（本轮用血换的）

1. **验收只以 B 口径（可见根数）为准**；C 口径（叶子）仅旁证，引用必须带「定义 + 采集时刻 + 来源方」——同角色叶子出现过 279/140/53、294/153/62、306/153/65 三套。
2. **同名字不同数一律带作用域**：47/40（根菜单）、391/279/153（总数 vs 叶子）、357/419（edu_nav 声明 vs 全部受保护，base 65 vs 66）。
3. **跑计数型验证前**先确认最近有没有跑过 `-u edu_life`（演示播种会写业务表；t12 后已确定性，但仍按此检查）。
4. **会写环境的验证（跑 `-u`）必须预约窗口 + 按批**：`safe_upgrade.sh` 每次都会 `restart web`，逐模块 ⇒ 升级风暴（本轮发生过两次，把并发冒烟打成"同一份代码三种形态"）；窗口前**同时排查外队进程**。
5. **假绿三律**：探测函数不得跟随重定向（`allow_redirects=False` + Location 精确）；**期望项数 == 实际项数**（死代码会静默少跑却报 PASS）；**阴性证据不能用于排除**（"日志里没有 INSERT" ≠ 没写）。
6. **暂存区是共享资源**：提交只用 `git commit -- <path>`，避免卷走他人 staged 文件。
7. 红线：零业务记录删除、不碰 `openeducat_erp/`、不碰生产、每步独立 commit 可回滚。

## 四、环境事实（很重要）

这台机器上的本地栈被**多个会话共享**：本仓同时还有另一个团队在做**权限可达性 / portal** 那条线（例：`2773ffe feat(perm): 教务后台可达性巡检…`、`9e5c07c test(portal): t2 …（portal-eng）`）。它会跑模块升级、重启 web 容器、甚至删升级锁 ⇒ **任何验证窗口前都必须先排查外队进程**（`ps aux | grep -E "safe_upgrade|verify_upgrade|backoffice_reachability|authz_|smoke"`）。
