# 发现 F1：菜单收口值在「升级其它模块」后被重放（t2 残留风险，实测成立）

- 发现人：verifier（T7 独立验证，只读实测）
- 日期：2026-09-17
- 影响任务：t2（菜单收口）验收条目「改动在升级后可复现」
- 严重度：**high / blocker**（不是误报；已可复跑复现）

## 1. 复现（一条命令）

```bash
python3 tests/audit/verify_upgrade_persistence.py --modules edu_portal --restore
```

输出（节选）：

```
升级前 B: {'admin': 18, 'backoffice': 12, 'faculty': 9, 'student': 0, 'parent': 0}
[run] bash scripts/safe_upgrade.sh -u edu_portal       # EXIT=0, 无 Traceback
  -> edu_portal   REPLAY  B={'admin': 23, 'backoffice': 17, 'faculty': 12, ...}
[run] bash scripts/safe_upgrade.sh -u edu_nav          # EXIT=0
  复原后 B: {'admin': 18, 'backoffice': 12, 'faculty': 9, 'student': 0, 'parent': 0}
== 结论: 以下模块升级后重放了收口值: edu_portal
```

## 2. 证据

| 项 | 值 |
|---|---|
| 升级前 active 菜单 | 514 |
| `-u edu_portal` 后 active 菜单 | **519（+5）** |
| 全库菜单数（含 inactive） | 605 → 605（**未增未删**，红线遵守） |
| 口径 A 根菜单 | 40 → 40（记录未动） |

复活的具体 5 棵根菜单（子项随根一起恢复可见）：

| id | 名称 | 归属 xmlid | 原模块 |
|---|---|---|---|
| 542 | 邀请码 | `edu_portal.menu_edu_invite_code_root` | edu_portal |
| 543 | 日常管理 | `edu_portal.menu_edu_welfare_root` | edu_portal |
| 576 | 在线课程 | `edu_portal.menu_edu_lms_root` | edu_portal |
| 597 | 行政评估 | `edu_eval.menu_edu_admin_eval_root` | edu_eval |
| 606 | 老账号补挂身份 | `edu_portal.menu_edu_relink_identity` | edu_portal |

口径 B 变化：admin 18→23、backoffice 12→**17（超验收线 12）**、faculty 9→12。
⇒ 也就是说：**跑一次 `-u edu_portal`，教务口径立刻从达标变回不达标**。

对照组（说明不是"所有升级都重放"）：
- `-u edu_life`：各角色 B 与 active 菜单数**完全不变**（18/12/9、514）→ PASS
- `-u edu_nav`：把被重放的值**再修回来**（23/17/12 → 18/12/9）→ 可恢复

## 3. 机制（已定位到记录级）

1. t2 的收口值写在 `custom_addons/edu_nav/data/menu_consolidation_data.xml`，
   用 `<record id="<其它模块>.<xmlid>">` 覆盖 40 棵根菜单的 `active / groups`。
2. 这批 xmlid 的 `noupdate` **全是 0**（全库 605 条 `ir.ui.menu` 的 noupdate 也全为 0）。
   ⇒ 引用它们的模块每次 `-u` 都会把 `active / groups` 写回**自己 XML 里的声明值**。
3. 542/543/576/606 在 `edu_portal/views/*.xml` 里是 `<menuitem ... groups="...">`，
   597 在 `edu_eval/views/eval_views.xml` 里同理。
   ⇒ `-u edu_portal` 时 edu_portal 后跑，把 t2 的 `active=False` 覆盖成 `True`。
4. 谁最后跑谁赢：`-u edu_nav` 又把它盖回来（所以"再 -u edu_nav 就恢复"）。

注：档 2 的六棵（1/15/121/142/196/566）**没被重放**——实测其 groups 只有
`base.group_system`(gid=4)，说明这些在 XML 里没有 groups 声明、t2 的改动就活了下来；
被重放的恰好是「XML 里有 groups/active 声明」的那几棵。

## 4. 建议的修复方向（交由队长派 repair，verifier 不改实现）

任选其一，须满足「任何模块 `-u` 之后收口值都仍然成立」：

1. **在 edu_nav 里做 post-init/post-upgrade 钩子重放**（推荐）：
   `post_init_hook` 之外再加一个每次升级都执行的 `_post_init` 逻辑（如
   `models.py` 里用 `ir.ui.menu` 的 get-or-apply，幂等），保证 edu_nav 值在
   *所有* 模块升级后仍是最后写入者。缺点是别的模块升级后仍可能盖回去 —— 所以要么
2. **让引用方的 XML 声明与收口值一致**：即不靠 edu_nav 覆盖，而是直接改
   `edu_portal/views/*.xml` / `edu_eval/views/*.xml` 里这几条 `<menuitem>` 的
   `active/groups`（或去掉 `groups` 声明），从源头消除"声明值 ≠ 收口值"。缺点：动多个模块。
3. **给这些 xmlid 置 `noupdate=1`**（改 `ir_model_data`），使模块升级不再重放它们。
   缺点：会让这些菜单的记录脱离声明式管理，需与回滚脚本一起评估。

## 5. 复验方法（repair 后请跑这两条）

```bash
python3 tests/audit/verify_upgrade_persistence.py --modules edu_portal,edu_life,edu_eval
python3 tests/audit/verify_consolidation.py --phase after     # 口径 B 应稳定 18/12/9/0/0
```

判定：`verdict` 全 PASS（各角色 B 与升级前一致、active 菜单数不变）。

## 6. 当前状态（截至本次实测）

- 已复原：B = admin 18 / backoffice 12 / faculty 9 / student 0 / parent 0，active 514。
- 未核：其它可能重放收口值的模块（凡 edu_nav 引用其 xmlid 的模块）。
  edu_nav 引用到的模块有：
  account、base、board、calendar、contacts、data_recycle、edu_apply、edu_eval、edu_portal、edu_quiz、event、hr、hr_attendance、hr_recruitment、hr_recruitment_skills、im_livechat、mail、openeducat_admission、openeducat_assignment、openeducat_attendance、openeducat_core、openeducat_exam、spreadsheet_dashboard、utm、website_livechat、website_slides、website_slides_forum。
  ⇒ 建议 repair 后把这批模块逐个跑一遍 `verify_upgrade_persistence.py`，
  确认没有第二个"重放源"。
