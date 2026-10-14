# 发现 F5：edu_life 在 `-u` 时向业务表注入「无标记演示数据」（滚动窗写法）

- 发现人：verifier（T7 独立验证）；由 data-eng 在 F3 归因中提示（编号 F5，避免与 t7 报告中 F4=未核范围 混淆），verifier 独立复核并界定边界
- 日期：2026-09-17
- 严重度：**medium**（不影响现有记录，但污染业务表且会随日历推移增长）
- 归属建议：t6（防复发闸门 / 落地前查重）

## 1. 机制

`custom_addons/edu_life/data/demo_life.xml` 末尾：

```xml
<function model="edu.checkin.type" name="_load_demo_records"/>
```

该文件位于 manifest 的 **`data`**（非 `demo`）列表 ⇒ **每次 `-u edu_life` 都执行**。
`models/checkin_type.py:62` 的 `_load_demo_records()` 逻辑：

```python
today = datetime.date.today()
plan = [(bible.id, range(0, 7)), (devotion.id, range(1, 7))]   # 滚动近 7 天
for type_id, offsets in plan:
    for offset in offsets:
        day = today - datetime.timedelta(days=offset)          # 相对"今天"
        if Record.search_count([...]):                          # 先查重
            continue
        Record.create({...})                                    # 再写
```

写入目标 `edu.checkin.record` **是业务表**，不是 `demo` 表。

## 2. 边界界定（verifier 实测，纠正"不幂等"的笼统说法）

| 场景 | 实测 | 结论 |
|---|---|---|
| 同一日历日重复 `-u edu_life` | count **53 → 53**，净增量 **0** | **幂等**（`search_count` 查重生效） |
| 跨日历日再跑（T+1 之后） | 未实测（需等到明天） | **会新增**：窗口右移，新的一天若无记录即被补写 |

⇒ 准确表述是：**「对同一 (学生,类型,日期) 幂等，但对时间不幂等」**——
它按"今天"取滚动 7 天，所以只要日历前进且中间没跑过，就会补写缺失日。
**代码注释里只写了"方法内部幂等"，漏了"相对今天滚动"这一维**，这是需要修正的认知点。

## 3. 真正的风险（比增长本身更重要）

1. **无【演示】标记**：`Record.create()` 只写 `student_id / type_id / checkin_date`，
   不带任何标记字段。这 9 条与真实打卡**混在同一张业务表**里，
   事后只能靠 `create_uid=1 + create_date 同秒 + student_id=5(stu@local)` 反推。
   而仓库规范要求「演示数据带【演示】」——此路径**不符合**。
2. **升级即写业务数据**：任何一次 `-u edu_life`（含生产级升级）都会执行。
   虽然当前只针对 `stu@local`，但这是"升级动作改业务表"的模式，
   与「收口只隐藏/迁移、可回滚、可审计」的原则相冲突。
3. **口径污染**：教师统计 / 学生打卡页会把演示行计入。
   本轮 `-u edu_life` 已实测使 `edu_checkin_record` 净增 9 条（36→45 时段），
   直接导致 t9 的「旧表零增长」断言无法成立（须改口径为"迁移以外无新增"）。

## 4. 建议（交 t6 / 队长裁定）

1. 把该 `<function>` 从 `data/` 移到 **`demo/`**（`demo_life.xml` 改由 `demo` 键引用），
   使非演示环境不再执行。
2. 或在函数内加环境闸门（如 `ir.config_parameter` 开关 / `--without-demo` 判断）。
3. 若确需保留，至少给写入行加『【演示】』标记，便于与真实数据区分与清理。
4. 顺带修正文档/注释：「幂等」应写明是"同日幂等 + 滚动 7 天窗口"。

## 5. 未核

- 跨日历日的新增行为未实测（需要时间推进；建议明日或改系统时钟后复测）。
- `edu.journal.entry` 同类写入（同函数后半段）是否也有同样的"已存在即跳过"行为——
  从代码看有 `search_count` + 直接 `return`，**未实测**。
