# 菜单收口前后对照表

- 收口前基线：`docs/audit/menu-consolidation/menu-tree-before.json`
- 收口后基线：`docs/audit/menu-consolidation/menu-tree-post_nav_reupgrade.json`

> 生成器：`scripts/menu_baseline_diff.py`（纯文件比较，无需连库，验证方可独立复算）

## 0. 口径数字（改的是开关，不是记录数）

| 口径 | 收口前 | 收口后 | 变化 |
|---|---|---|---|
| A 原始根菜单（parent_id IS NULL，含 inactive） | 40 | 40 | +0 |
| A 其中 active | 39 | 39 | +0 |
| A 其中 inactive | 1 | 1 | +0 |
| 全库菜单数（含 inactive） | 605 | 605 | +0 |
| 全库 active 菜单数 | 601 | 601 | +0 |

## 1. 分角色可见口径（B 可见根 / C 可见叶子 / 可见总数）

| 角色 | B 前 | B 后 | ΔB | C 前 | C 后 | ΔC | 总数前 | 总数后 |
|---|---|---|---|---|---|---|---|---|
| admin | 38 | 38 | +0 | 400 | 400 | +0 | 551 | 551 |
| backoffice@local | 31 | 31 | +0 | 279 | 279 | +0 | 391 | 391 |
| faculty@local | 19 | 19 | +0 | 115 | 115 | +0 | 164 | 164 |

## 2. 逐角色：不再可见的根菜单 → 新路径 / 确认下线

### admin：不再可见 0 个根菜单

- （无变化）

### backoffice@local：不再可见 0 个根菜单

- （无变化）

### faculty@local：不再可见 0 个根菜单

- （无变化）

## 3. 字段级改动清单（active / 父菜单 / 排序 / 可见组 / 名称）

| menu id | 菜单 | 字段 | 前 | 后 |
|---|---|---|---|---|
| - | （无改动） | - | - | - |

# 汇总：字段级改动 0 条；被隐藏记录数（active True→False）= 0；硬删除记录数 = 0
