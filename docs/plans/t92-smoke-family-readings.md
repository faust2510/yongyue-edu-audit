# §3.6 全量门禁复跑（t92 定稿：健康窗口实测）
> **状态**：`归档` ｜ **主题**：`门禁冒烟读数` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 环境读数：MEASURED_AT **00:22:07** ｜ daemon **29.4.1** ｜ db **Up 12h healthy** ｜ web **Up 14 分钟** ｜ 探活 `/web/login?db=edu19` = **302** ｜ 负载 **5.04/6.41/10.18**（10 核）｜ `odoo shell` **秒回 SHELL_OK** ✓
> 出处列：`clean`=已入库；`M`=有未提交改动（dirty）。**本批对 `p5_acd/aux2/ux_batch4_a1/aux3` 为混版**（i18n-eng `838cd2d` 落于批次中途）→ **不作 after 快照**。

## 一、三件门禁
本轮只跑家族（门禁读数见 t79 段）：check_odoo_trace 指纹 1886da9b/断言 40/四维 0 命中；check_english v3.4 指纹 f7580f6c/断言 33（含运行时刻）；check_view_xpath RESULT=OK 指纹 a1066767。

## 二、冒烟家族（rc / PASS / FAIL / 首个失败断言名 / 出处）
**绿且与 t79 一致**：F_roles rc=0 P=12 ｜ p2_enroll rc=0 P=13 ｜ p3_prod_ledger rc=0 P=22 ｜ p3_prod_receipt_acl rc=0 P=10 ｜ H_event_acl rc=0 P=7 ｜ c_http rc=0 P=5 ｜ 另有 D_public / audit_completeness / aux1 / aux4 / c_browser / data_driven_brand_leak / downloads_v2 / gate_seam_check / make_report / notice_privilege / p5b / p5f / smoke_a_routes / smoke_common / smoke_livechat / ux_v3_route_matrix / ux_week_utils_check / write_route_liveness / zero_loss_reachability = rc=0（这些用非 `[PASS]` 格式输出，P/F=0 属格式差异，非早退）

**t79 为红 → 本批转绿（i18n-eng 修复；混版，不作 after 快照）**
| 脚本 | t79 | 本批 |
|---|---|---|
| p3_ledger_smoke | rc=1 F=1 | **rc=0 P=26 F=0** |
| ux_batch4_a1_approval_smoke | rc=2 F=1 | **rc=0 P=27 F=0** |
| aux2_batch_smoke | rc=1 | **rc=0** |
| p5_acd_smoke | rc=1 | **rc=0** |
| aux3_batch_smoke | rc=1 F=5 | **rc=0** |

**仍红（脚本陈旧 → t90 剩余部分）**
| 脚本 | rc | P | F | 首个失败断言名 | 出处 | 定性 |
|---|---|---|---|---|---|---|
| G_messages_smoke | 1 | 20 | 5 | `S9 GET /my/messages/poll 学生`（unread=323） | clean | 绝对未读基线 → 待改相对/增量 |
| smoke_student | 1 | 5 | 3 | `#8 登录后落 /my/home 且功能卡网格≥10张` | clean | 旧选择器/旧期望（与 t79 完全相同 → 仍是同一条） |
| smoke_anon | 0 | 7 | 0 | —— | **M（dirty）** | t90 的 #7 改动未入库未评审；本批以该版本跑出 7/7 绿，**仅作该版本的运行时观察**，不作已验证结论 |

**新发现（退出码契约缺口）**：`E_quiz_cross.py` **rc=0 但 F=1**（`B8 日志巡检(45m) :: 30 行新增错误日志`）→ 与 t86 修掉的同类（有 FAIL 却给 0）→ 建议并入 t90 剩余部分。

**登记不纳入**：`ux_rework_*`（8 个）+ `tmp_t3_attack_*`（3 个）rc=1 = seed/probe/一次性复现、非独立可跑；`_fixtures.py`=夹具模块；`authz_endtoend_smoke.py` 本批 SKIP（i18n-eng 窗口）。

## 三、assertion_audit 复查
见 `/tmp/t92b_audit.log`；t86 旧读数（rc=0 / REVIEW 40 / 被环境吃掉 0 / 次数不足 328）作历史锚点。

## 四、口径声明（定稿）
1. **三件门禁绿 ≠ 冒烟家族全绿**：本批家族仍有 `G_messages` / `smoke_student` / `E_quiz_cross` 红。
2. **看 FAIL 前先看 PASS**：`PASS=0` 即早退、整批作废；本批无早退。
3. **对照按断言名**：`smoke_student` 与 t79 失败断言名**完全相同** → 判"仍是同一条"；`G_messages` 同族（未读基线）。
4. **混版读数**：批次中途有提交（`838cd2d`）→ 4 个脚本不作 after 快照；**绝不以"提交前跑出的红"证明修复无效**。
5. **出处效力**：`M`（dirty）读数的结论效力受限（`smoke_anon`）。
6. **已作废读数**（不再引用）：t86 `PASS=0` 早退 / t90 第一步 `#FATAL` 超时 / 冻结期 `000` 未跑。
## 五、t106 收口：三条红项转绿（after = **确定版本**）

**版本出处**：3 个脚本本次无未提交改动，跑的就是提交态；文件 md5 ——
`G_messages_smoke.py` `6bd279d090259c221959809621c0c8e7`、
`smoke_student.py` `2684434a1c9faa5fb67235235f5ef5f7`、
`E_quiz_cross.py` `56a9b636b204f610dde2fcc0178de820`。
（**与 §4 第 4 条不同**：t92 那批是混版、不作 after；本批是**确定版本**。）

**运行时刻**：2026-09-13T21:57:39+0800 / 2026-09-14T08:59:59+0800。
**进程表快照**：两次运行前后 `tests/smoke` 进程数均为 **0**（无并发）。

| 脚本 | before（t92） | after（本批） | 首个失败断言名 |
|---|---|---|---|
| `G_messages_smoke.py` | rc=1 ｜ P20 F5 | **rc=0 ｜ TOTAL 25 FAIL 0** | 前：`S9 GET /my/messages/poll 学生`（`poll unread=323`）；后：**无** |
| `smoke_student.py` | rc=1 ｜ P5 F3 | **rc=0 ｜ 8/8 PASS** | 前：`#8 功能卡网格≥10`；后：**无** |
| `E_quiz_cross.py` | **rc=0 但 F=1** | **rc=0 ｜ PASS3 WARN2 FAIL0** | 前：`B8 日志巡检(45m)`（30 行）；后：**无** |

**逐条对照（按断言名）**
1. `S9 GET /my/messages/poll 学生`：FAIL（绝对基线，实测 unread=323）→ **PASS**（改紧邻基线 `U9`，实测 `unread=380 基线U9=380 增量=0`）；
2. `S13 教师读后未读清零`：FAIL（要求全局 unread=0，实测教师另有会话未读 11/20）→ 更名 `S13 教师读后该会话未读清零`、改看被打开会话 → **PASS**；
3. `S14c 学生主页 私信提醒卡+铃铛`：落点陈旧 → 更名 `S14c 学生应用页(/my/apps) …`（batch2.xml:1035 / `edu_dashboard_v2` 由 batch2.py:1942 `/my/apps` 渲染）→ **PASS**；
4. `#8 登录后落 /my/home 且功能卡网格≥10张`：FAIL（卡片已迁 /my/apps）→ 拆成「落点 /my/home」+「网格去 /my/apps 数」→ **PASS**；
5. `#9 …?w=-1 空态文案且日期范围早7天`：FAIL（`empty=False`，判据隐含「上一周必然没课」，数据依赖）→ 改判**渲染自洽（空态 XOR 表格恰其一）+ 周偏移早 7 天** → **PASS**；
6. `#10 课程→课次→详情`：FAIL（`course#46:lessons=0`）→ 查明是**数据条件**（该生档案 id=9 只挂科目 46，8 条课次在 35/36/37＝别的课程）⇒ 有课次走完整链路、无课次退化为断言科目页渲染自洽**并在证据里点名哪段无法构造** → **PASS**；
7. `E_quiz_cross` rc 语义：原**无 `sys.exit`**（有 FAIL 也返 0）→ 加 `exit(1 if n_fail else 0)`，**用 1 不用 2/3**（2/3 会被 `ENV_RCS` 判环境型而漂白）→ rc=0（本轮 0 FAIL，语义已对齐）。

**`assertion_audit.py --selftest`**：10/10 PASS（含「rc=2 单独即判环境型」「rc=3 单独即判环境型」「ENV 日志不吃 runs」等反例）。

**边界说明**：`smoke_anon.py` 的 t90 遗留改动由队长处置（已入库、工作区干净），不在本节范围。
