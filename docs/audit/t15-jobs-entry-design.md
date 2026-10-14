# t15 设计稿（只读准备）：让 `/jobs` 空页入口不再出现，且**再升一次仍为 0**

> 责任：menu-eng ｜ 日期：2026-09-17 ｜ 状态：**设计完成，等 t13 解锁后执行**（本轮未跑任何 `-u`）
> 关联：F7（t10 终态后新立）、`scripts/check_nav_jobs_entries.py`、`tests/unit/check_nav_jobs_entries_test.py`

## 0. 结论先行（方案选择）

| 项 | 事实/决定 |
|---|---|
| `/jobs` 入口的**唯一稳定业主** | **menu 206**（它当前持有 xmlid `website_hr_recruitment.website_menu_jobs`） |
| 原生定义位置 | `odoo/addons/website_hr_recruitment/data/config_data.xml:13-18`（`<record id="website_menu_jobs" model="website.menu">`，**记录键就是该 xmlid** ⇒ 全库只会有一条） |
| 孤儿 | **menu 205**（无任何 xmlid 归属）——由并发/试错产生的重复，**删除** |
| **推荐修法** | `edu_nav` 数据文件按**规范 xmlid 覆盖 206**：`url = /campus/jobs`、`name` 中文化（+ `active`? 见 §3 取舍），随后对同一 xmlid 置 **`noupdate=1`** |
| 备选修法 | `edu_nav` 的幂等 `<function>`：每次装载后按 `url='/jobs'` 清理（删除或改指） |

**为什么推荐前者**：206 的记录键是原生 xmlid，`noupdate=1` 一旦置上，`-u website_hr_recruitment` 就
**不会再写回**（源码依据：`_load_records: if not (update and d_noupdate)`；`_build_update_xmlids_query` 的
`ON CONFLICT DO UPDATE` 不含 `noupdate`）。而 `<function>` 属于"每次装载都跑一遍"的清理，
**只要有人 `-u` 该模块而 edu_nav 不在同一条升级链里，就可能出现"短窗口内又长回来"**；且 `<function>` 删记录
与"零删除"的偏好相冲（删的是配置数据，但仍不如"改指 + 保护"干净）。

## 1. 免 `-u` 的静态取证法（用于证明"保护已就位"）

```sql
-- 206 是否已持有原生 xmlid（决定走"覆盖+保护"还是"清理"）
select module||'.'||name from ir_model_data where model='website.menu' and res_id=206;      -- website_hr_recruitment.website_menu_jobs
-- 该 xmlid 是否已受保护
select noupdate from ir_model_data where module='website_hr_recruitment' and name='website_menu_jobs';
-- 是否仍有指向空页的入口
select count(*) from website_menu where url='/jobs';
```

## 2. 执行步骤（t13 解锁后，逐条留证）

```bash
# ① 只读：确认现状与业主
python3 scripts/check_nav_jobs_entries.py --verbose
psql: select id,url,parent_id from website_menu where url='/jobs'      # 期望 205(孤儿)+206(原生)

# ② 标注期望态进计划（不手改库）：在 edu_nav 数据文件里为规范 xmlid 声明
#    url=/campus/jobs、name 中文化；并把它纳入"受保护"清单
python3 scripts/gen_menu_data.py --state=baseline        # 生成声明式数据
python3 scripts/check_menu_data_sync.py                  # XML ↔ dry-run 目标态对账（0 漂移才算好）

# ③ 落库（**需要队长窗口**——会重启 web）
python3 scripts/consolidation_persist.py --unprotect      # 解开保护（若该 xmlid 已受保护）
bash scripts/safe_upgrade.sh edu_nav                      # 普通 <record> 重放 → 写 url/name
python3 scripts/consolidation_persist.py --protect        # 上保护（幂等，带备份）

# ④ 清孤儿 205（非规范业主）
python3 scripts/fix_nav_duplicates.py --apply             # 按 url 全量识别

# ⑤ **核心判据**：再升一次原生模块，仍为 0（**需要窗口**）
bash scripts/safe_upgrade.sh website_hr_recruitment
python3 scripts/check_nav_jobs_entries.py                 # 期望 rc=0
python3 scripts/check_nav_reachable.py                    # 期望 24/24
```

## 3. 两处必须**先决定**的取舍（我给出建议，等你裁）

1. **206 /jobs 的去向**：改指 `/campus/jobs`（保留一个有效入口，导航条数回到 38）**还是** `active=False`
   （彻底不显示，回到 37）？
   - 建议 **改指 `/campus/jobs`**：它本来就是"工作机会"的同一类入口，改指比停用更符合"不新增、只减死胡同"；
     且 188「工作机会」已指向同一 URL，两个入口同名同目标会被"重复入口"判据盯上——
     **若要严格保持 0 个 /jobs、且不与 188 重复，则选 `active=False`**。请裁一个。
2. **`active` 字段能否经该 xmlid 写入**：`website.menu` 无 `active` 字段（实测字段表里没有），
   停用要么用 `is_visible=False`，要么直接删除该记录。若选"停用"，我需要先确认 `is_visible` 的实际效果
   （前端是否真的不渲染）——**这一步要跑 HTTP 验证，不涉及 `-u`**。

## 4. 验收对应（队长给的 3 条 + 我的 2 条）

| 验收 | 证据形式 |
|---|---|
| 清掉 205/206（第一步） | `check_nav_jobs_entries.py --verbose` 列出 → `--apply` → 再查为 0 |
| **再 `-u website_hr_recruitment` 一次仍为 0** | 步骤 ⑤ 的窗口内读数（含窗口时间） |
| 修法持久（优先 noupdate；无 xmlid 则 edu_nav 覆盖或幂等 function） | 本设计 §0 的判据表 + §1 静态取证（`noupdate` 位） |
| 哨兵纳入验收 | `scripts/check_nav_jobs_entries.py`（已重构为可测结构） |
| 两个假绿缺陷做成回归用例 | `tests/unit/check_nav_jobs_entries_test.py` **19/19 PASS**（含"证伪旧写法"的对照断言） |

## 5. 本轮（只读准备）已完成 / 未做

- ✅ 查明原生定义与 xmlid 归属（206=业主、205=孤儿）；写出两方案与判据；哨兵重构 + 19 条回归用例（`1add197`）。
- ⛔ 未做（等 t13 解锁 + 窗口）：任何 `-u`、任何对 205/206 的写操作。
