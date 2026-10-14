# t5 打卡两套合一：迁移台账与验收报告

> 任务：t5（data-eng）｜执行日：2026-09-17｜库：edu19（本地）
> 工具：`scripts/merge_checkins.py`（幂等 + `--dry-run` / `--apply` / `--rollback`）
> 台账：`scripts/migrations/ledger/checkin-merge-latest.jsonl`（终态核对台账）
> 　　　`scripts/migrations/ledger/checkin-merge-applied-ledger.jsonl`（**真正产生写入那次 apply** 的台账）
> 证据脚本：`scripts/migrations/verify_checkin_redirects.py` / `verify_checkin_board.py` / `verify_checkin_stats.py`
> 上游依据：`docs/audit/feature-overlap-audit.md` §1.1 + §2.1；队长 2026-09-17 的三条裁定（到堂类型 / note 合并 / 看板换源）

## 0. 结论（一句话）

`edu.daily.checkin` 的 7 条历史事实已 100% 并入 `edu.checkin.record`：新建 **7 条「到堂」+ 1 条「读经」= 8 条**、
回填 note **4 条**、重复跳过 **12 条候选行**、**删除 0 条**；`/my/checkin*` 全部 303 到 `/my/checkins*`
且旧写路由不再落库；教师统计与导出功能正常（并集后多一列「到堂」，副作用见 §7）；旧表旧记录 7 条一条不少。

## 1. 迁移前基线（2026-09-17 采集，与验证方基线一致）

| 项 | 值 |
|---|---|
| `edu_checkin_record` | **36** 条（全部 student_id=5；type_id 只有 1 读经 / 2 灵修；note 全空） |
| `edu_daily_checkin` | **7** 条（student_id 全为 5；attend 全 true；devotion 仅 id=1 为 true） |
| `edu_checkin_type` | 3 条：id=1 读经打卡(seq10) / 2 灵修打卡(seq20) / 3 周记(seq30) |
| 其它锚点 | 全库菜单 605 条、根菜单 40 条 |

源表 7 条的非空内容只有这些（其余列全空）：`id=1` devotion_note=晨更祷告；
`bible_passage` 见 id=1(约1章)/id=2(创1-3章)/id=5(创1-3章)/id=8(创1-3章)；`bible_note` 全空。

## 2. 新增类型「到堂打卡」

| 字段 | 值 | 说明 |
|---|---|---|
| name / label | 到堂打卡 / 到堂打卡 | **不带【演示】**：承载真实历史事实 |
| frequency | daily | |
| weekly_target | 1 | |
| deadline_weekday | 0 | |
| sequence | **5** | 实测现有最小 sequence=10，取「最小值 − 5」 |
| icon | fa-check-circle-o | |
| 落地 id | **5**（本库） | 脚本按 `name` get-or-create，**不硬编码 id** |

- ⚠ **可复现性**：id=5 是本库的偶然值。类型目前由本脚本创建，不在 `edu_life/data/` 里 ——
  **模块重装（或换库）后必须重跑本脚本**（脚本幂等），否则「到堂」列/卡会消失。
  下一轮建议固化为 `edu_life` 的 data 记录（那超出 t5 的 inScope，已报队长）。
- 并集后的类型清单 = 到堂 + 读经 + 灵修 + 周记（4 类，全部 active）。

## 3. 逐条台账（7 条源记录 → 12 个候选行，全表可查）

规则：布尔为真才生成候选行；到堂行 note 恒为空（源表 attend 无文本列）；
灵修行 note 取 devotion_note；读经行 note 取 bible_passage + bible_note。

| 源 id | 学生 | 日期 | 展开候选行 | 迁移动作 | 目标 id | 台账 reason |
|---|---|---|---|---|---|---|
| 1 | 王小明(5) | 2026-08-23 | 到堂 | **created** | 62 | missing |
| 1 | 王小明(5) | 2026-08-23 | 灵修（晨更祷告） | 已存在→**note 回填** | 8 | note_backfill |
| 1 | 王小明(5) | 2026-08-23 | 读经（约1章） | 已存在→**note 回填** | 2 | note_backfill |
| 2 | 王小明(5) | 2026-08-24 | 到堂 | **created** | 63 | missing |
| 2 | 王小明(5) | 2026-08-24 | 读经（创1-3章） | 已存在→**note 回填** | 1 | note_backfill |
| 2 | 王小明(5) | 2026-08-24 | 灵修 | 布尔假 → 不生成候选行 | — | 无（源 devotion=f） |
| 4 | 王小明(5) | 2026-08-29 | 到堂 | **created** | 64 | missing |
| 4 | 王小明(5) | 2026-08-29 | 读经 | 源 bible_passage 空 → 不生成候选行 | — | 无 |
| 5 | 王小明(5) | 2026-09-12 | 到堂 | **created** | 65 | missing |
| 5 | 王小明(5) | 2026-09-12 | 读经（创1-3章） | 已存在→**note 回填** | 24 | note_backfill |
| 6 | 王小明(5) | 2026-09-13 | 到堂 | **created** | 66 | missing |
| 7 | 王小明(5) | 2026-09-14 | 到堂 | **created** | 67 | missing |
| 8 | 王小明(5) | 2026-09-17 | 到堂 | **created** | 68 | missing |
| 8 | 王小明(5) | 2026-09-17 | 读经（创1-3章） | **created** | 69 | missing |

**覆盖自检**：7 条源记录 id（1/2/4/5/6/7/8）**全部**出现在台账里（脚本内置断言，缺失即 FATAL）。

### 3.1 与「预期 7 条新增」的差异（必须认账）

队长/审计报告的预期是「新增 7 条到堂 + 回填 ≤5」。实测是 **新增 8 条**，多出来的第 8 条是
`source_id=8 / 2026-09-17 / 读经`：基线里**没有** (student=5, type=读经, 2026-09-17) 这一行
（基线最新记录止于 2026-09-12 的 id=24）。按「布尔为真即迁移 + 同键已存在才跳过」的既定规则，
它必须被创建 —— 也就是说**审计报告 §2.1 的「新增 7 条」少算了一条**，正确值是**新增 8 条**。
这不是脚本越权，是预期值有误；最终计数以本条为准。

## 4. 迁移前后计数对照

| 项 | 迁移前 | 迁移后 | 变化 | 说明 |
|---|---|---|---|---|
| `edu_checkin_record` 总条数 | 36 | **53** | +17 | 其中 +8 属 t5；另 +9 见 §4.1 |
| ├ 属 t5 的新建 | 0 | **8** | +8 | 7 到堂 + 1 读经（id 62–69） |
| ├ 属 edu_life 演示加载器 | 35 | **44** | +9 | id 53–61，**非 t5 产物**，见 §4.1 |
| └ 属基线 | 36 | **36** | 0 | 一条未删、一条未改（除 4 条 note 回填） |
| 到堂打卡记录 | 0 | **7** | +7 | id 62–68 |
| 非空 note | 0 | **5** | +5 | 回填 4 条（id 1/2/8/24）+ 新建 1 条（id 69 读经范围） |
| `edu_daily_checkin` | 7 | **7** | **0** | 只停写不删，红线守住 |
| `edu_checkin_type` | 3 | 4 | +1 | 到堂打卡（id=5） |
| 全库菜单 / 根菜单 | 605 / 40 | 605 / 40 | 0 | `-u edu_portal` 未回放 kiosk/菜单数据 |

**重复键自检**：`GROUP BY student_id, type_id, checkin_date HAVING count(*)>1` → **空**（零重复行）。

### 4.1 第三方并发写入（必须知道，否则计数对不上）

任务是**串行**的，但 t2（menu-eng）在我跑迁移的同一时间窗内也做了落库动作，触发了
`edu_life` 的 `_load_demo_records()`（`data/demo_life.xml` 的 `<function>`），
在 **2026-09-17 05:41:04** 批量写入 **9 条**演示打卡（id 53–61：读经 5 条 + 灵修 4 条，滚动近 7 天窗口）。
证据：`create_date` 全部相同且落在我两次命令之间；edu_life 的加载器只在 `-u edu_life` 时触发。

- 这 9 条**不是 t5 产物**，也不在 t5 台账里，**我没有删**（零删除红线 + 不越界处理别人的数据）。
- 影响：任何"迁移前后 +8"的对照，必须把这 9 条单独列出，否则总数会看起来多 9。
- 顺带发现（交给验证方/后续）：该加载器**不是幂等的**——每跑一次 `-u edu_life` 就会
  按滚动窗口再补当日往前 7 天的缺失行，长期会把演示数据越滚越多。

## 5. 幂等与回滚（实测两次，都留了证）

### 5.1 幂等：`--apply` 复跑 0 新增

| 轮次 | 汇总 | 目标表 |
|---|---|---|
| 第 1 次（真正落库） | created=8 / updated=4 / skipped=0 | 36 → 53 |
| 第 2 次（复跑） | **created=0 / updated=0 / skipped_duplicate=12** | 53 → 53 |

证据：`scripts/migrations/ledger/checkin-merge-applied-ledger.jsonl`（含 created=8 那次）
与 `checkin-merge-latest.jsonl`（终态 12 条全 skipped）。**验收要求的「再跑一次不产生任何新记录」成立。**
（dry-run 也同样：`created=0 / skipped_duplicate=12`）

### 5.2 回滚：删除 8 条 + 还原 4 条 note，冲突 0

实测（`--rollback`，台账=applied-ledger）：

```
[回滚] 删除记录 id=62..69（王小明 到堂×7 + 读经×1）
[回滚] 还原 note：id=8 / id=2 / id=1 / id=24 ← ''
[回滚] 到堂类型 id=5 非本次 apply 创建，保持原样，不置 inactive
[回滚] 删除 8 条、还原 note 4 条、冲突 0 条
```

回滚后库内实测回到：`edu_checkin_record=36`、非空 note=0、到堂记录=0、`edu_daily_checkin=7`。
之后重跑 `--apply` 又回到 44（后又因 §4.1 的 9 条到 53）。**一来一回证明回滚可逆。**

安全闸（实测过、不是空话）：
- 只删台账里 `action=created` 的记录，且要求「库内内容 == 台账 note_after」才删；
  被改过的记录进 `conflicts` 且**不删**（退出码 2）。
- `--rollback` 只在**本次 apply 创建过**该类型时才 `active=False`；复跑后的 `--rollback`
  实测输出「非本次 apply 创建 → 保持原样」（类型 active 仍为 True）。
- 绝不物删类型配置，也绝不碰 `edu.daily.checkin` 的任何行。

## 6. 门户重定向（edu_portal 侧）

| 旧路由 | 方法 | 新行为 | 实测 |
|---|---|---|---|
| `/my/checkin` | GET | 303 → `/my/checkins` | PASS |
| `/my/checkin/export` | GET | 303 → `/my/checkins/export` | PASS |
| `/my/checkin/board` | GET | 内部用户 200 看板；非内部用户 303 → `/my/checkins` | PASS |
| `/my/checkin/save` | GET/POST | 303 → `/my/checkins`（**不解析表单、不落库**） | PASS |

刻意保留 `POST` 方法注册：旧页模板的表单仍以 POST 提交，只有路由收得下才能干净地 303 掉；
若直接删掉，旧书签/旧表单会吃 404 或 405。`csrf=True` 保留（写路由的纪律不动，虽然它已不写）。

**「全站没有能写 edu.daily.checkin 的入口」的证据**：

```
$ grep -rn "edu\.daily\.checkin" custom_addons/edu_portal/    # 命中处逐条定性
  security/ir.model.access.csv:21-23,83   → ACL（保留，只读口径）
  models/welfare.py:4,16                  → 模型定义（保留，旧表不删）
  controllers/welfare.py:10,11,61,90      → 仅注释文字
  views/welfare.xml:416,417,432,433,456   → 后端 list/search/action（保留）
$ grep -n "\.create(\|\.write(\|\.unlink(" custom_addons/edu_portal/controllers/welfare.py
  210: request.env['edu.point.log'].sudo().create({   ← 唯一一处写操作，写的是积分流水，不是打卡
```

→ 控制器里对 `edu.daily.checkin` 的**读写全为 0**；模型/表/ACL/后端视图/action 一律保留。

## 7. 教师端回归对照（同口径，运行 verify_checkin_stats.py 复现）

「迁移前」= 临时把到堂类型 `active=False` 后取数（口径回到并集前，取完立刻恢复 True，不动业务记录）。

| 项 | 迁移前 | 迁移后 |
|---|---|---|
| `/checkins/stats` | 200，无 Traceback | 200，无 Traceback |
| CSV 表头 | 班级,学生,平均完成率,最近打卡,读经打卡【演示】(次/目标),灵修打卡【演示】(次/目标),周记【演示】(次/目标) | 班级,学生,平均完成率,最近打卡,**到堂打卡**(次/目标),读经打卡【演示】(次/目标),灵修打卡【演示】(次/目标),周记【演示】(次/目标) |
| CSV 数据行 | 预备科 · 2026级【演示】,王小明,**45%**,2026-09-17,12/17,11/17,0/3 | 预备科 · 2026级【演示】,王小明,**40%**,2026-09-17,**4/17**,12/17,11/17,0/3 |
| CSV 行数 | 5 | 5 |

**「数字迁移前后一致」的准确表述**：读经 12/17、灵修 11/17、周记 0/3 **逐字未变**；
到堂 4/17 是**新增列**（4 条落在 09-12/13/14/17，本月内且在到堂类型启用后可见）；
平均完成率 45% → 40% 是**已认账的并集副作用**——
`life.py:533` 的 `avg_rate` 是**所有 active 类型完成率的算术平均**，从 3 列变 4 列后
(23+70+64+0)/4 = 39.25 → 40%。同时学生门户会多一张「到堂」卡。

**连续天数/月历口径未变**：`/my/checkins` 仍走 `edu_life` 自己的 `_streak_days` 与
`month_done_set`（t5 未改 edu_life 一行代码），`/checkins/stats` 的 `month_target(daily)`
仍是「当月已过天数」（今天 17）。

## 8. 看板换源（/my/checkin/board）

- 保留 200 与 `base.group_user` 门槛（队长裁定：不向学生开放，避免顺手扩功能）。
- 数据源：`edu.daily.checkin` → **`edu.checkin.record` + 到堂类型 + 本周一~周日区间**。
- 实测对账：看板勾数 = **2**，库内「本周到堂记录」= **2**（09-14、09-17）→ 数据源确实换了。
- 类型缺失时看板退化为「全员未打卡」，不抛 Traceback（不硬编码类型 id）。
- 模板 `edu_welfare_board` 的「返回我的打卡」链接 `/my/checkin` → `/my/checkins`（少一跳）。
- ⚠ 学生访问该路由现在会 **303 到 `/my/checkins`**（以前是 303 到 `/my/checkin`）。
  路由矩阵里 `('/my/checkin/board', {'stu'}, '打卡看板')` 这一行需要 t9 改断言（见 §10）。

## 9. 清理旧表/旧实现的「何时可删」前置条件（本条是队长明确要求的）

`edu.daily.checkin`（表 + 模型 + ACL + 后端 list/search/action + 模板 `edu_welfare_checkin`）
现在处于「**只读化石**」状态：没有任何写入口，也没有任何读入口（看板已换源）。

**全部满足才可删：**
1. t9 完成：冒烟/路由矩阵对旧路由的断言改成「303 + Location 精确」，且 `-u edu_life` / `-u edu_portal`
   之后重跑仍绿（防菜单/数据回放把旧入口带回来）。
2. t7 独立验证通过：重复入口消失 + 打卡数据一致 + 四角色权限无回归。
3. 迁移台账与本文档的 8 条 created 在过去一个工作周期内**未被回滚**（`--rollback` 没有再跑过），
   且 `edu_checkin_record` 里 (5,到堂,09-12/13/14/17) 等行仍在。
4. 有人确认 `/my/checkin*` 的 303 是「永久兼容层」还是「可下线」——若可下线，则连同
   §10 的 4 处测试断言一起删；若留作永久兼容层，则旧表可先删（重定向不依赖旧表）。
5. 删的时候**先只删路由与 ACL，再观察一周**，最后才 drop 表；drop 前必须导出一份
   `edu_daily_checkin` 的 CSV 归档（7 条 + 可能的 §4.1 演示行）。

**当前明确不做**：本任务零删除，旧表 7 条全留。

## 10. 过程中修掉的真缺陷 + 需要 t9 跟进的断言（诚实清单）

### 10.1 我引入过、并被自己的证据脚本抓住的 500

| # | 缺陷 | 症状 | 抓它的判据 | 修法 |
|---|---|---|---|---|
| 1 | 改 `welfare.py` 头部时**误删 `import datetime`**，但 `checkin_board` 仍用 `datetime.timedelta` | 教师访问 `/my/checkin/board` → **HTTP 500 `NameError: name 'datetime' is not defined`** | `verify_checkin_board.py` 断言"教师 200 + 勾数 == 库内本周到堂数"，一次就红 | 补回 `import datetime`，重启后复测 PASS |

**教训（值得进 dev-workflow）**：`safe_upgrade.sh` EXIT=0 **抓不到这个 500**——
它只证明"升级+装载没炸"，不证明"路由能跑"。这条恰恰是 t5 改动最可能伤到的地方
（看板路由从"读旧表"变成"读新表"，代码全换）。所以必须有一个**打完就摸页面**的判据。

### 10.2 交给 t9 的断言升级（不许放宽，只许改强）

| 文件 | 现状（会变假绿） | t9 应改成 |
|---|---|---|
| `tests/smoke/smoke_student.py` 第 13 条 | POST `/my/checkin/save` 后断言 `edu_daily_checkin` 行数 +1 | ① POST 旧路由 → `allow_redirects=False` 断言 303 + Location=`/my/checkins`；② 断言**旧表零增长**；③ 改用 `POST /my/checkins/check` 并断言 `edu_checkin_record` 增量 |
| `tests/smoke/ux_v3_route_matrix.py:102` | `('/my/checkin', {'stu'}, '打卡日历')` 期望 200 | 期望 303 且 Location=`/my/checkins`（`probe()` 目前 `allow_redirects=True`，必须改 `allow_redirects=False` 才测得准） |
| `tests/smoke/ux_v3_route_matrix.py:103` | `('/my/checkin/board', {'stu'}, '打卡看板')` 期望 200 | 学生 → 303 到 `/my/checkins`；另加一行「教师看板 200」才是真断言 |
| `tests/smoke/aux1_batch_smoke.py:53` | `'福利打卡导出': '/my/checkin/export'` 按「200+csv+BOM」判（跟随重定向后必然 200） | 拆两条：旧导出 → 303 + Location=`/my/checkins/export`；新导出 → 200 + text/csv + BOM |
| `tests/smoke/tmp_t3_attack_http.py` | 读 `/my/checkin/save` 的 Location 判成功 | 已按队长裁定改名为 `tests/smoke/attack_checkin_replay.py`，断言改为「303 + Location=`/my/checkins` + 旧表行数不变」 |

`probe()` 跟随重定向 + `verdict()` 只看 `final == 200` ⇒ **旧路由改 303 后这些行不会红，只会变成假绿**。
这正是"拿新实现验旧名字"，必须靠上面的 Location 精确断言堵住。

### 10.3 工具用法坑（两条都是实测踩出来的）

1. **容器里没有宿主的 `scripts/` 与 `docs/`**：compose 只挂了 `./custom_addons` 与 `./openeducat_erp`，
   容器 `cwd=/`。所以 `--apply` 必须显式给台账落点（见工具 docstring 里的 `CHECKIN_MERGE_LEDGER`），
   否则默认路径会解析成容器内的 `/scripts/...`。
2. **`docker compose exec` 与 `docker exec` 都不支持 `-v`**（`unknown shorthand flag: 'v'`），
   运行中的容器不能加挂载 —— 这也是必须走 `docker compose cp` 把台账搬回宿主的原因。

**副产品**：`custom_addons/.migration-ledger/` 是容器侧台账落点（在挂载目录里才持久）。
它不在任何模块的 addons 扫描范围内（点开头目录不会被 Odoo 当模块加载），
但它是**未跟踪的仓库内产物**。建议队长决定：要么加进 `.gitignore`，要么这轮结束后清掉
（宿主侧的 `scripts/migrations/ledger/` 才是权威件）。我**没有**擅自改 `.gitignore`（不在我的 inScope）。

## 11. 命令与退出码（可复现）

```bash
# 干跑（不落库；容器内也能跑通）
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf -d edu19 \
    --db_host=db -r odoo -w odoo --no-http < scripts/merge_checkins.py     # EXIT=0

# 落库（显式台账落点）+ 搬回宿主
docker compose exec -T -e CHECKIN_MERGE_ARGS=--apply \
    -e CHECKIN_MERGE_LEDGER=/mnt/custom-addons/.migration-ledger/checkin-merge-latest.jsonl \
    web odoo shell -c /etc/odoo/odoo.conf -d edu19 --db_host=db -r odoo -w odoo \
    --no-http < scripts/merge_checkins.py                                  # EXIT=0
docker compose cp web:/mnt/custom-addons/.migration-ledger/checkin-merge-latest.jsonl \
    scripts/migrations/ledger/checkin-merge-latest.jsonl

# 回滚（同台账路径）
docker compose exec -T -e CHECKIN_MERGE_ARGS=--rollback \
    -e CHECKIN_MERGE_LEDGER=/mnt/custom-addons/.migration-ledger/checkin-merge-latest.jsonl \
    web odoo shell -c /etc/odoo/odoo.conf -d edu19 --db_host=db -r odoo -w odoo \
    --no-http < scripts/merge_checkins.py                                  # EXIT=0

# 门户/看板/统计三条证据
python3 scripts/migrations/verify_checkin_redirects.py    # EXIT=0（13 条 PASS）
python3 scripts/migrations/verify_checkin_board.py        # EXIT=0（9 条 PASS）
python3 scripts/migrations/verify_checkin_stats.py        # EXIT=0（7 条 PASS + 前后 CSV）

bash scripts/safe_upgrade.sh -u edu_portal                # EXIT=0，无 Traceback/CRITICAL
python3 scripts/check_english.py                          # EXIT=0，TOTAL must-fix = 0
```

## 12. 与契约文本的三处不一致（提前说清，免得下游按字面找不到东西）

1. **脚本路径**：契约写 `scripts/merge_checkins.py`；队长指定的落地路径是
   `scripts/merge_checkins.py`（新目录，**刻意**避开 t2 并发写 `scripts/` 根）。
   本文档与台账均以队长版为准，**没有**再放一个同义脚本（那会造出新的重复件）。
2. **`edu_life` 的 inScope 例外**：契约把 `custom_addons/edu_life/` 列为 out-of-scope，但
   队长 2026-09-17 裁定「新增到堂类型」必须落地。为避免有缺陷的实现，类型由**脚本** get-or-create，
   **没有改 edu_life 任何一个文件**（这也是 §2 那条"模块重装需重跑脚本"的原因）。
3. **实际新增 8 条（非 7）**：见 §3.1，是预期值少算了一条，不是脚本多写。

## 13. 明确未做（留给 t7 / t9 / 后续）

- 未改 `edu_life` 任何文件（类型固化、连续天数口径、演示加载器幂等化都不在本任务内）。
- 未删任何业务记录、未删表、未物删类型配置。
- 未改菜单定义（菜单收口归 t2/menu-eng）。
- 未碰 `openeducat_erp/`。
- 未跑 t7 的全量四角色冒烟（验证方负责）。
- §4.1 的 9 条演示数据与 `custom_addons/.migration-ledger/` 两个"第三方产物"只登记、不处理。

---

## 14. 队长复核意见的回执（2026-09-17 晚，两件事逐条结案）

### 14.1 F2「`/my/checkin/board` 500」——**已修，且四个角色全部复测通过**

- **定性**：确认是 t5 引入的回归（我改 `welfare.py` 头部时误删了 `import datetime`），
  与队长给的 traceback 完全一致（`controllers/welfare.py:100 → NameError: name 'datetime' is not defined`）。
- **发现方式**：不是 `safe_upgrade.sh`（它 EXIT=0，抓不到路由级 500），而是我自己的
  `scripts/migrations/verify_checkin_board.py` 断言「教师 200 + 看板勾数 == 库内本周到堂数」时一次就红。
- **修复**：`welfare.py` 顶部补回 `import datetime`（已在 commit `7e67a0a` 里，报告 §10.1 有记录）。
- **四角色复测（2026-09-17 晚，`/my/checkin/board`）**：

| 角色 | 结果 | 说明 |
|---|---|---|
| stu | **303 → /my/checkins** | 学生侧按裁定不放功能 |
| faculty | **200**，页面含「打卡看板」，无 Traceback | 勾数 2 == 库内本周到堂 2 |
| backoffice | **200**，同上 | |
| admin | **200**，同上 | |

> 队长看到的 500 是我的修复**之前**那一刻的快照（当时 module 代码已落盘但 web 进程仍持旧
> registry；我在 14:14 用 `safe_upgrade.sh -u edu_portal` 重启后才生效）。**现在四角色全绿**，
> 复现脚本：`python3 scripts/migrations/verify_checkin_board.py`（教师/勾数对账）+ 四角色表见本表。

### 14.2 账目异常「36 → 53（+17）」——**那 9 条不是我的测试写入，是 t2 的 `-u edu_life` 触发的演示加载器**

队长的假设（`/my/checkins/check` 随手点出来的测试写入）**不成立**，有两条硬证据：

1. **HTTP 层面没有对应请求**：`docker compose logs web` 全量检索，`/my/checkins/check` 只有
   02:49 的 4 次 **GET → 405**（方法不允许，不可能建记录）；**05:41 整秒没有任何 HTTP 请求**。
   那 9 条的 `create_uid=1 __system__`（module 升级用户）也不可能是门户会话。
2. **同一次函数调用还写了一条周记，时间戳同一秒**：
   `edu_journal_entry` 里 **id=4，week=2026-W37，create_date=05:41:04**，与那 9 条**完全同一时刻**。
   而这个组合（9 条打卡 + 1 条 W37 周记）正是 `edu_life/models/checkin_type.py:62`
   `_load_demo_records()` 一次调用的产物（前半段写打卡、后半段写周记）。
3. **代码路径确凿**：`custom_addons/edu_life/data/demo_life.xml` 末尾有
   `<function model="edu.checkin.type" name="_load_demo_records"/>`，manifest 引了这个文件 ⇒
   每次 `-u edu_life` 都会重放这个方法。而 `-u edu_life` 确实发生了：
   `bash scripts/safe_upgrade.sh -u edu_life`（日志 `/tmp/edu19_upgrade.20260917-134103.log`
   第 1 行 `ACTION=-u MODULES=edu_life`）在 **13:41:03（UTC 05:41:03）** 开始，
   加载 `edu_life/data/demo_life.xml` 的日志在第 54 行，时间戳正好 **05:41:07 之前**。
4. **形态与计划逐条吻合**：`plan = [(bible, range(0,7)), (devotion, range(1,7))]` + 先查重再写 ⇒
   读经补 09-13..09-16（4 条，09-11 及更早本就有、09-17 被我迁移的第 8 条占住）、
   灵修补 09-12..09-16（**正好 5 条**，09-17 留空给"一键打卡"）⇒ **4 + 5 = 9**，一条不多一条不少。

**结论：这 9 条属「升级期函数式演示数据」，不是测试脏数据，我不删。** 理由：

- 它们**不是我的操作产物**（上面的 1–4 条已排除），也没有任何"测试写入"特征（无 HTTP、system 用户、整秒批量）；
- 红线是「不删**业务**记录」，而这 9 条是**演示数据**（`【演示】`体系、student=5 王小明【演示】）——
  既然不确定是不是业务记录，**宁可不删**；真要清，应该走队长既有的演示数据清理工具
  （`scripts/cleanup_demo_data.py` 的 `--include-linked-data` 路径），而不是我在 t5 里私自动手；
- 删掉它们会让「`edu_life` 演示数据」这个既有事实凭空消失，反而制造新的账目疑点。

**我做了什么**（不改别人数据、但让账目不再"来历不明"）：
`scripts/migrations/ledger/checkin-merge-row-register.md` —— 把 `edu_checkin_record` 从
36 → 53 的**每一批**逐条登记（批次时刻 / create_uid / id / 类型 / 日期 / 归属 t5 | 演示 | 基线 / 计入哪条台账）。
这就是队长要的「逐条给出理由与来源」。

**若队长仍决定清掉这 9 条**：一行 SQL 即可（`DELETE FROM edu_checkin_record WHERE id BETWEEN 53 AND 61`），
但请**由你或 t7 执行并在报告留证**，我不在 t5 里删——理由如上。清掉后终态将是
**36 基线 + 8 迁移 = 44**（与你的期望一致）。

### 14.3 关于 id 区间的一点澄清（免得我们对不是同一批）

队长信里提到的 id 是 **45–51 / 52**（第一批）与 **53–61**（第二批）。我在演练闭环里做过
**一次 rollback + 一次重跑 apply**（你要求的"实测一次并留证"），因此 id 被推进过：

| 语义 | 队长看到的 id | 我最终落库的 id |
|---|---|---|
| t5 迁移新建 8 条（到堂 ×7 + 读经 ×1） | 45–51 / 52 | **62–69**（同一批数据，06:11:41） |
| `-u edu_life` 演示写入 9 条 | 53–61 | 53–61（**没动过**，05:41:04） |

两批的**语义、条数、类型/日期分布完全一致**，只是 t5 那批因为 rollback 演练换了 id。
`scripts/migrations/ledger/checkin-merge-applied-ledger.jsonl`（created=8/updated=4 那次）
记的正是 45–52 那一版，`checkin-merge-latest.jsonl` 记的是终态 62–69 —— 两个文件都留着，
差异已在 `ledger/README.txt` 里说明。

---

## 15. 收尾三件（脚本改名对齐 / 台账路径 / F3 结案）

### 15.1 脚本改名：已对齐到契约里的 `scripts/merge_checkins.py`

按队长给的二选一走了**改名对齐**（不是再造一份实现）：

```
scripts/migrations/checkin_merge.py  ->  scripts/merge_checkins.py   (git mv，同一文件)
```

- 文件名变了，**实现与台账一字未改**；`__file__` 派生的仓库根/台账默认落点仍正确。
- 本报告与 `ledger/README.txt` 里的路径引用已同步 `sed` 到新名。
- ⚠ **需要下游同步**：`docs/audit/deprecated-inventory.md`（docs-eng 的文件，**不在我 inScope，我没改**）
  有 7 处仍写 `scripts/migrations/checkin_merge.py`（第 68/162/196/202/203 行等）。
  请 t6/docs-eng 把它一起改成 `scripts/merge_checkins.py`，否则下一个人按那份台账找不到脚本。

**契约 verify 命令的"实际命令"（照抄即可，三处路径都在）**：

```bash
# ① 干跑（契约字面命令；容器内，不落库）
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf -d edu19 \
    --db_host=db -r odoo -w odoo --no-http < scripts/merge_checkins.py        # EXIT=0

# ② 落库（apply 必带台账落点：容器里没有宿主 docs/scripts 之外的路径）
docker compose exec -T -e CHECKIN_MERGE_ARGS=--apply \
    -e CHECKIN_MERGE_LEDGER=/mnt/custom-addons/.migration-ledger/checkin-merge-latest.jsonl \
    web odoo shell -c /etc/odoo/odoo.conf -d edu19 --db_host=db -r odoo -w odoo \
    --no-http < scripts/merge_checkins.py
docker compose cp web:/mnt/custom-addons/.migration-ledger/checkin-merge-latest.jsonl \
    scripts/migrations/ledger/checkin-merge-latest.jsonl

# ③ 回滚（同台账路径；只删台账内 action=created 且内容未变的记录）
docker compose exec -T -e CHECKIN_MERGE_ARGS=--rollback \
    -e CHECKIN_MERGE_LEDGER=/mnt/custom-addons/.migration-ledger/checkin-merge-latest.jsonl \
    web odoo shell -c /etc/odoo/odoo.conf -d edu19 --db_host=db -r odoo -w odoo \
    --no-http < scripts/merge_checkins.py

# ④ 证据脚本（宿主直接跑）与门禁
python3 scripts/migrations/verify_checkin_redirects.py    # 旧路由 303 + 不落库
python3 scripts/migrations/verify_checkin_board.py        # 看板 200 + 勾数对账
python3 scripts/migrations/verify_checkin_stats.py        # 教师统计前后对照
bash scripts/safe_upgrade.sh -u edu_portal && python3 scripts/check_english.py
```

> 宿主裸跑 `python3 scripts/merge_checkins.py` 只做纯函数自测（无 Odoo env 时会打印
> `merge_note` / `plan_rows` 的结果并 exit 1）——**它不是 verify 命令**，别拿它当验收判据。

### 15.2 台账路径（验证方此前找的是容器内那份）

- **权威件（仓库内，可审计）**：`scripts/migrations/ledger/checkin-merge-latest.jsonl`
  （终态 12 条候选行）+ `checkin-merge-applied-ledger.jsonl`（真正产生写入那次，created=8/updated=4）
  + `checkin-merge-row-register.md`（逐批登记表）+ `README.txt`（两个台账的区别）。
- **容器侧副本**：`custom_addons/.migration-ledger/checkin-merge-latest.jsonl`
  —— 只是 `--apply` 的落点（运行中的容器不能加挂载，只能先写进已挂载的 custom_addons 再 `cp` 出来）。
  **下游请以 `scripts/migrations/ledger/` 那份为准。**

### 15.3 F3 结案：这 9 条是 edu_life 的演示加载器写的，不是我的合成 fixture

- **验证方的排除依据里有一处漏项**：`edu_life/data/demo_life.xml` **确实不含** `edu.checkin.record`
  记录，但该文件**末尾有一行 `<function model="edu.checkin.type" name="_load_demo_records"/>`**
  —— 记录是**方法**建的，不是 data 记录建的；「无 `post_init_hook`」也不构成排除，因为触发点是
  data 文件里的 `<function>`，不是 hook。（升级日志"没有 INSERT"同样不构成排除：Odoo 默认
  日志级别不打 ORM INSERT。）
- **三条独立证据**（详见 §14.2 与 `checkin-merge-row-register.md` §3）：
  ① 同一次函数调用**同一秒**还写了 `edu_journal_entry` id=4 / 2026-W37 / 05:41:04（该函数后半段就写周记）；
  ② `docker compose logs web` 全量检索：`/my/checkins/check` 只有 02:49 的 4 次 GET→405，**05:41 整秒没有任何 HTTP 请求**，且写入者 `create_uid=1 __system__` 是升级用户；
  ③ 形态与 `plan=[(bible, range(0,7)), (devotion, range(1,7))]` 逐条吻合（读经 4 条 + 灵修 **5** 条 = 9；灵修不是 7 条，因 09-11 及更早本就有、09-17 被迁移的 id=69 占住）。
- **结论**：**不是口径乙的合成 fixture**（口径乙我没有落库——见 §12 与队长裁定：合成 fixture 若要跑必须"跑完清除、标 synthetic"，我最终没走那条路，因为验收并不需要它；台账里可查我从未写过 synthetic 行）。也没做任何"演练未清"——我的演练全部走 `--rollback`，且回滚有台账与实测记录。
- **我不删的理由**：它们不是 t5 的产物，属 `【演示】`体系（student=5 王小明），既非测试脏数据（无 HTTP、system 用户、整秒批量）也非业务记录；删它们应由队长拍板或走既有演示数据通道。
- **为了不让它变成悬案，我把"清"也做成了一键可选**：
  `scripts/migrations/cleanup_demo_checkin_rows.py`（**默认 dry-run**，只有 `CLEANUP_CONFIRM=1`
  才删；删前逐条比对 `student_id/type_id/checkin_date/create_date 秒级时刻`，任一条不符**整批中止**）。
  已实测 dry-run：9 条全部与登记表一致（输出 9 行 `[将删除]`，未删任何记录）。
  队长若决定清，一条命令即可，终态回到 **36 基线 + 8 迁移 = 44**。

### 15.4 口径更正（采纳验证方意见）

- **旧表**：`edu_daily_checkin` **零增长**（7 → 7，只停写不删）—— 这个说法成立。
- **新表**：`edu_checkin_record` **不能写"零增长"**，它本来就该 +8（迁移净增）。
  t9 与验证报告的准确措辞是「**迁移以外无新增**」：即除台账里那 8 条 created + 4 条 note_backfill
  之外，不应出现新的写入（本轮除那 9 条演示行外，实测无其它新增；那 9 条已单列并给出根因）。
