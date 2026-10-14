# 发现 F3（已更正归因）：9 条 `edu_checkin_record` 来自 edu_life 升级期 `<function>` 回调

> **更正说明（2026-09-17，verifier 复核后修订）**
> 本文初版判「来源不明」，并写「已排除 edu_life 模块数据路径」——**该结论错误**。
> 经 data-eng 指出、verifier 独立复核（§1.0/§1.1/§2.1 三重证据），根因确定为
> `custom_addons/edu_life/data/demo_life.xml` 末尾的 `<function>` 回调。
> **这不是数据丢失，也未违反任何红线。** 初版错误与错因保留在 §4 以免后来人重踩。

- 发现人：verifier（T7 独立验证，只读）
- 日期：2026-09-17
- 严重度：**medium**（非数据丢失；但增量口径需解释，否则 t9 断言会误判）
- 状态：**已归因、已定性、未删除**；防复发问题另立 **F5**

---

## 1.0 根因（已证实）

`custom_addons/edu_life/data/demo_life.xml` 末尾：

```xml
<function model="edu.checkin.type" name="_load_demo_records"/>
```

`custom_addons/edu_life/models/checkin_type.py:62` 的 `_load_demo_records()`：

```python
today = datetime.date.today()
plan = [(bible.id, range(0, 7)), (devotion.id, range(1, 7))]   # 滚动近 7 天
for type_id, offsets in plan:
    for offset in offsets:
        day = today - datetime.timedelta(days=offset)
        if Record.search_count([...]):   # 先查重
            continue
        Record.create({...})             # 再写
# 后半段还会写一篇 edu.journal.entry 周记
```

`edu_life/__manifest__.py` 把 `data/demo_life.xml` 放在 **`data`**（非 `demo`）列表
⇒ **每次 `-u edu_life` 都执行该函数**。

## 1.1 双向证据：代码 + 数据形态逐条对齐

设执行日 T = 2026-09-17：

| 类型 | plan offsets | 应有日期窗口 | 实测新建 | 被跳过的（因已存在） |
|---|---|---|---|---|
| 读经 (1) | `range(0,7)` | 09-11..09-17 | 09-13..09-16（4 条） | 09-11（id 25，09-12 建）、09-12（id 24，09-12 建）、09-17（t5 迁移产物） |
| 灵修 (2) | `range(1,7)` | 09-12..09-17 | 09-12..09-16（5 条） | 09-17（不在 `range(1,7)` 内；本就没有） |

- **同一时间戳**：`id 53..61` 的 `create_date` 全为 **`2026-09-17 05:41:04`**（同秒 9 条）、
  `create_uid = 1 __system__` ⇒ 一次函数调用，非真人逐条打卡。
- **数量吻合**：4（读经）+ 5（灵修）= **9**，与实测一致。
- **时间窗吻合**：`05:41:04` 正是 `-u edu_life` 的 loading 窗口
  （日志 `/tmp/edu19_upgrade.20260917-134103.log` 第 1 行 `ACTION=-u MODULES=edu_life`，
  并含 `loading edu_life/data/demo_life.xml`）。

## 2.1 补强证据（verifier 独立复核）

1. **同一次调用还写了周记**：`edu_journal_entry` **id=4 / `week=2026-W37` / `create_uid=1` /
   `create_date=09-17 05:41:04`** —— 与打卡 9 条**同一秒**；而 `_load_demo_records()` 后半段
   正是写周记 ⇒ **打卡 9 条 + W37 周记 = 一次调用的两半产出**。
2. **HTTP 层无对应写入**（排除"人工/门户写入"）：全量检索 `docker compose logs web`——
   `05:41:0x` 秒内**没有任何 werkzeug 请求行**（仅 worker 退出/registry 日志）；
   `/my/checkins/check` 全历史只有 **02:49 的四次 `GET ... 405`**（方法不允许，建不了记录）。
   且 9 条为 `create_uid=1 __system__`（模块升级用户），**门户会话不可能以该 uid 写入**。
3. **形态与 `plan` 逐条吻合**（见 §1.1）。

⇒ **写入方 = edu_life 模块 data 文件里的 `<function>` 回调**；触发路径
`bash scripts/safe_upgrade.sh -u edu_life`。

## 2.2 事实（终态，写入方已核）

- `edu_checkin_record`：基线 36 + t5 迁移 **8**（到堂 7 + 读经 1）+ edu_life 演示 **9** = **53**。
- 那 9 条（id 53–61）**仍在库中，未被删除**；属 `【演示】`体系、`student_id=5`（王小明）。
- `edu_daily_checkin` 全程 **7 条**未动；`(student_id,type_id,checkin_date)` 重复组 = **0**。
- 权威台账：`scripts/migrations/ledger/checkin-merge-latest.jsonl`（终态）、
  `checkin-merge-applied-ledger.jsonl`（产生写入那次）、`checkin-merge-row-register.md`（36→53 逐条登记）。
  容器侧 `custom_addons/.migration-ledger/` 仅为 apply 落点，**不作权威件**。

## 2.3 处置：**队长裁定保留，本轮不执行清理器**

> **裁定（队长，2026-09-17）**：那 9 条**保留**，本轮**不跑**清理器。四条理由：
> ① 属【演示】体系（student=5 王小明），非脏数据；
> ② 台账已**闭合**（36 基线 + 8 迁移 + 9 演示 = **53**）且逐行登记在册，可审计；
> ③ **删了会掩盖「升级即写业务表」这个真问题**；
> ④ t12 治本后若仍要清爽化，再单列一步、单独回滚。
> 清理器留在仓库备用（默认 dry-run），本轮**不跑**。

- 现状**未删**，且按裁定**本轮不删**。
- 提供 `scripts/migrations/cleanup_demo_checkin_rows.py`：**默认 dry-run**，`CLEANUP_CONFIRM=1` 才删；
  删前逐条比对 `student_id/type_id/checkin_date/create_date 秒级时刻`，任一条不符**整批中止**。
- verifier 实测 dry-run（odoo shell 内，`rc=0`）：9 条**全部相符**、**未删除任何记录**，
  跑前跑后计数均为 **53** ⇒ 清理器不越界、不误删。

## 3. 影响

1. **t9 断言口径必须是「迁移以外无新增」**，不能写「零增长」：
   `edu_checkin_record` 本轮**本就该 +8**（到堂 7 + 读经 1），另有 edu_life 演示 +9。
2. 数据面未见重复（已实测），源表未删 ⇒ **红线未破**。
3. 防复发（该 function 放在 `data/` 且写业务表、无【演示】标记）另立 **F5** 交 t6。

## 4. 初版结论为何错（留档）

初版的三条依据本身都对，但**推论错了**：

| 初版依据 | 是否成立 | 为什么不能用于排除 |
|---|---|---|
| `demo_life.xml` 里搜不到 `edu.checkin.record` | 成立 | 记录不是 data **记录**建的，而是文件末尾 `<function>` **回调方法**建的 |
| 升级日志没有对 `edu_checkin_record` 的 INSERT | 成立 | Odoo 默认日志级别**不打印 ORM INSERT**（阴性证据） |
| 模块无 `post_init_hook` | 成立 | 触发点是 data 文件里的 `<function>`，**与 hook 无关** |

**教训**：查"谁写的"不能只看 data 记录与 hook，**必须连带看 `<function>` / server action**；
"日志里没有"这类阴性证据不能用于排除。

## 5. 建议

1. 已采纳：t9 断言改口径为「迁移以外无新增」。
2. F5 处理：把该 `<function>` 移出 `data/`（改由 `demo/` 引用）或加环境闸门，至少给写入行加【演示】标记。
3. 台账/清理器保持"默认 dry-run + 逐条校验"的模式（本轮实测安全）。

## 6. 未核

- 跨日历日再跑 `-u edu_life` 的新增行为（机器日期即 09-17，未推进；见 F5）。
- `edu.journal.entry` 同函数后半段的查重行为（代码看有 `search_count` 后直接 `return`，**未实测**）。
- 9 条**无【演示】标记**这一点已核；但其是否属于「【冒烟】/【演示】」规范范围，需 t6 裁定。
