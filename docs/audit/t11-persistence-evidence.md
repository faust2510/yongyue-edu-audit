# t11 证据：菜单收口的「重放」修复与持久性实测

> 责任：menu-eng ｜ 日期：2026-09-17 ｜ 环境：本地 edu19
> 关联：F1（t7 提出）、`scripts/consolidation_persist.py`、`tests/audit/verify_upgrade_persistence.py`
> 根因与修法的完整推导见 `docs/audit/consolidation-persistence-fix.md`（本文件只放**验收证据**）

## 1. 验收口径的四条 verify（全部实跑）

| verify 命令 | 结果 |
|---|---|
| `python3 tests/audit/verify_upgrade_persistence.py --modules edu_portal --restore` | **PASS**（升级后 B = admin 14 / backoffice 12 / faculty 9） |
| `python3 tests/audit/verify_upgrade_persistence.py --modules edu_eval --restore` | **PASS**（同上） |
| `bash scripts/safe_upgrade.sh edu_nav` | 退出无失败特征 |
| `python3 scripts/verify_edu_nav.py` | **5/5 PASS** |

## 2. 逐个模块升级后仍保持收口（覆盖 edu_nav 引用的模块）

| 批次 | 模块 | 升级后 B | 判定 |
|---|---|---|---|
| 1 | edu_portal | 14 / 12 / 9 | ✅ |
| 2 | edu_eval | 14 / 12 / 9 | ✅ |
| 3 | edu_life / edu_apply / edu_quiz / base / mail / website | 14 / 12 / 9（6 个逐个） | ✅ |

另有一次**45 个归属模块一次性升级**（`account,mail,hr_recruitment,hr,website_slides,contacts,hr_attendance,hr_skills,
gamification,calendar,openeducat_core,im_livechat,data_recycle,utm,event,openeducat_exam,spreadsheet_dashboard,
hr_gamification,resource,account_payment,openeducat_attendance,website_slides_forum,openeducat_assignment,
onboarding,digest,iap,phone_validation,privacy_lookup,sms,website_livechat,base_automation,rating,
hr_recruitment_skills,auth_oauth,snailmail,board,base_import_module,web_tour,openeducat_admission,
hr_skills_slides,hr_skills_event,edu_portal,edu_eval,edu_apply,edu_quiz`）：无失败特征，
仍 **14/12/9**，全库 **605** / 根 **40** / 停用 **200**。

### 2.1 逐模块独立读数（13 个模块，全部保持 14/12/9）

**更正**：本文档上一版写"`hr` / `openeducat_*` 的独立批次读数没取到"——**那是错的**。
实测复查 `tests/audit/out/persistence_post_*.json` 发现这些批次**跑过并留下了完整读数**
（当时只是 stdout 被工具窗口吞掉，我没查产物就下了结论）：

| 模块 | B（admin / backoffice / faculty） | 全库 / 根 | 时间 | 判定 |
|---|---|---|---|---|
| edu_portal | 14 / 12 / 9 | 605 / 40 | 15:04:06 | ✅ |
| edu_eval | 14 / 12 / 9 | 605 / 40 | 15:04:20 | ✅ |
| openeducat_attendance | 14 / 12 / 9 | 605 / 40 | 15:08:20 | ✅ |
| openeducat_assignment | 14 / 12 / 9 | 605 / 40 | 15:08:36 | ✅ |
| edu_life | 14 / 12 / 9 | 605 / 40 | 15:09:18 | ✅ |
| edu_apply | 14 / 12 / 9 | 605 / 40 | 15:09:33 | ✅ |
| edu_quiz | 14 / 12 / 9 | 605 / 40 | 15:09:46 | ✅ |
| base | 14 / 12 / 9 | 605 / 40 | 15:09:57 | ✅ |
| mail | 14 / 12 / 9 | 605 / 40 | 15:11:06 | ✅ |
| website | 14 / 12 / 9 | 605 / 40 | 15:11:50 | ✅ |
| hr | 14 / 12 / 9 | 605 / 40 | 15:12:51 | ✅ |
| openeducat_core | 14 / 12 / 9 | 605 / 40 | 15:13:14 | ✅ |
| openeducat_exam | 14 / 12 / 9 | 605 / 40 | 15:13:30 | ✅ |

（每次含一次 `-u edu_nav --restore`；`persistence_post_restore.json` 亦为 605/40。）

### 2.2 关于"27 个模块"这个数量

队长口径里的"27 个模块"与实测不符，**实际是 46 个**：`edu_nav` 数据文件覆盖的 357 条菜单，
其 xmlid 归属 `select count(distinct module) …` = **46 个模块**（base 65 条 / account 53 / mail 33 /
hr_recruitment 27 / hr 18 / … / edu_portal 10 / openeducat_* 13 …）。
另一个易混点：`edu_nav` 的 `depends` **只声明了 `base`** —— 这不影响持久性，因为修法是
"给被覆盖记录的 xmlid 置 `noupdate=1`"，与模块加载顺序/依赖无关（§4 的反向验证直接证明）。

### 2.3 未能跑到全量 46 个的原因（环境，非技术）

逐个模块跑需要**独占升级锁**（约 1 次升级 + 1 次 restore 每次 ~1 分钟）。本轮尝试批量复现时
撞上**升级锁争用**：我的一次 `safe_upgrade` 被工具窗口 300s 超时杀掉、留下了残留锁，
而该锁又让**另一位成员的实验脚本**进入等待（其脚本注明最多等 30 分钟）。
处置：我终止自己的后台批量任务并清除由我造成的残留锁，**给他人让路**，不再抢锁。
⇒ 46 个模块的"逐个独立读数"未跑满；已用 13 个（含全部高风险模块）+ **45 个一次性合并升级**（§2）覆盖。

## 3. 5 棵复活根的逐条前后值

| id | 菜单 | 修复前（`-u edu_portal` 后实测） | 修复后（`-u edu_portal` + `-u edu_eval` 之后） |
|---|---|---|---|
| 542 | 邀请码 | active=True，groups=[4,40] | **active=False**，groups=[4,40]，xmlid noupdate=**True** |
| 543 | 日常管理 | active=True，groups=[1] | **active=False**，groups=[1]，noupdate=**True** |
| 576 | 在线课程 | active=True，groups=[1] | **active=False**，groups=[1]，noupdate=**True** |
| 597 | 行政评估 | active=True，groups=[1] | **active=False**，groups=[1]，noupdate=**True** |
| 606 | 老账号补挂身份 | active=True，groups=[4,40] | **active=False**，groups=[4,40]，noupdate=**True** |

（`groups` 保持原定义不变，改的只是 `active` 与 xmlid 的 noupdate 保护位。）

## 4. 修法持久性与「不依赖事后重跑」的直接证明

`verify_upgrade_persistence.py` 的判定是：**先记录升级前的 B，跑 `-u <他模块>`，再记录升级后的 B**。
PASS 意味着"只升级他模块、**没有**重跑 edu_nav"就能保持 —— 这正是"不依赖事后手动重跑"的证明。

反向验证（证明修法就是那条开关，不是巧合）：
```bash
python3 scripts/consolidation_persist.py --unprotect   # 撤销 noupdate 保护
bash scripts/safe_upgrade.sh edu_portal                # 只升级他模块
# → 5 棵确实复活：admin 19 / backoffice 17（超线）/ faculty 12
```
再按正确顺序恢复：`--unprotect → gen_menu_data.py --state=baseline → -u edu_nav → --protect` → 回到 **14/12/9**。

## 5. 副作用与后续维护规则（谁再改这些菜单该改哪里）

- **副作用**：被保护（`noupdate=1`）的 **357 条**菜单**不能再靠模块 XML 改**——改了不生效。
- **唯一入口**：菜单口径的声明源是 `custom_addons/edu_nav/data/menu_consolidation_data.xml`
  （由 `docs/audit/menu-consolidation/menu-consolidation-plan.json` + `scripts/gen_menu_data.py` 生成）。
  要改菜单，**必须**按这个顺序：
  ```bash
  python3 scripts/consolidation_persist.py --unprotect   # 1 解开保护（否则 edu_nav 自己也写不进）
  python3 scripts/gen_menu_data.py --state=baseline       # 2 从计划 JSON 重新生成数据
  bash scripts/safe_upgrade.sh edu_nav                    # 3 落库
  python3 scripts/consolidation_persist.py --protect      # 4 重新上保护
  ```
  只跑 2/3 会"升级成功但菜单没变"（noupdate 挡住了 edu_nav 自己）。
- 想彻底交还控制权：`--unprotect` 即还原（依 `nav-…`/`noupdate-backup.json` 备份）。
- 不影响这些模块的其它数据；**不新增、不删除任何 ir.ui.menu**（全库 605 不变）。

## 6. 红线自查

| 红线 | 实测 |
|---|---|
| 不新增/删除 `ir.ui.menu` | 全库 **605**（收口前后一致） |
| 根菜单 | **40** |
| active 根 | **14** |
| 可回滚 | `--unprotect`（保护位）/ `scripts/rollback_menus.py`（菜单值，基线驱动）双路 |

## 7. 「未穷举项」的处置（队长裁定：**不必补**）+ 一个更省环境的替代取证法

### 7.1 队长裁定（2026-09-17）：`hr / openeducat_*` 的独立批次**不必重跑**

理由（三条，队长给出、我认可）：
1. **45 个归属模块的一次性合并升级**已覆盖它们的重放路径；
2. 修法是**按 xmlid 设 `noupdate`、与模块名无关**；
3. §4 的**反向验证**（`--unprotect` 后 5 棵确实复活）直接证明机制成立。

⇒ 本文档 §2.3 里"未跑满 46 个"的开放尾，**到此关闭为"不补 + 理由"**，不再作为待办。

### 7.2 环境纪律（教训 + 以后的规矩）

- **教训**：逐模块 `-u` 会**反复重启 web 容器**（`safe_upgrade.sh` 设计上会 `restart web`）。
  我的一次 4 模块循环把**并发跑 t9 全量冒烟的队友**打成了"同一份代码三种形态"
  （升级日志 4–7s 一个、容器 10–45s 被 137 杀掉重启）。队长按进程参数定位后终止了我的扫描 —— **这是对的**。
- **规矩（今后）**：会改动/重启环境的验证**必须先预约静默窗口、并按批跑**（≤8 个模块/批），不得与他人验证并发。

### 7.3 替代取证法：**静态证明**，完全不需要 `-u`（强烈推荐给后续复核）

重放问题的本质是"被覆盖记录的 xmlid 是否 `noupdate=1`"—— 这是一个**纯数据库事实**，
因此可以**只读 SQL 直接证明**，既不动环境也不重启容器：

```sql
-- ① 收口目标（edu_nav 声明的 357 条）是否全部受保护？应 = 357
select count(*) from ir_model_data
 where model='ir.ui.menu' and res_id in (<357 个 id>) and noupdate=true;
-- ② 受保护集合的规模（报"防重放护住多少"用这个数）
select count(*) from ir_model_data where model='ir.ui.menu' and noupdate=true;   -- 419
-- ③ 这些 xmlid 归属多少模块（报覆盖范围用）
select count(distinct module) from ir_model_data
 where model='ir.ui.menu' and res_id in (<357 个 id>);                             -- 46
```

**实测结果（2026-09-17，零次 `-u`）**：① **357 / 357** 全部受保护；② **419**；③ **46 个模块**。
配合源码依据（`_load_records: if not (update and d_noupdate)`；`_build_update_xmlids_query` 的
`ON CONFLICT DO UPDATE` 不含 `noupdate`）即可**静态推出**"任何模块升级都不会写回这些记录"。
> 结论：后续若还要复核重放驻留，**优先用 §7.3 的静态取证**；只有在"要验证 odoo 实际行为"时才申请窗口跑 `-u`。
