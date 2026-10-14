# t45 复评报告（round-3）：t44 —— 评审人 i18n-eng
> **状态**：`归档` ｜ **主题**：`邮件去 Odoo 复评` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 复评对象：**t44**（repair-round-3，实现者 brand-eng，status=completed）
> 复评口径：沿用 t32 那条 —— **自己用忠实上下文实渲染，不拿 `--mail` 的绿作判据**；同时核对**探针是否已与忠实渲染同构**。
> 方法：`ir.qweb._render` 实渲染 + DB 查询 + 读码；未修改任何被测文件（复评只读）。

## 结论：**pass**

t44 的两条 acceptance 全部达成且我独立复现；t32 我打回的两条 high（F1 真实邮件泄漏 / F2 探针失真）**均已治根**。
**探针与忠实渲染现在同构到 1 字节**（28358 vs 28359），这是本轮最关键的一处结构性改善。

---

## 1. 逐条判定

### t44-AC1：覆盖 digest.digest_mail_main 的三块（横幅 / KPI 链接 / tips），并用忠实上下文复验 → ✅ 通过

我用忠实上下文（照 `digest/models/digest.py:_action_send_to_user` 逐字段构造，**用户取 ERP 管理员**）实渲染：

```
RENDER len=28359  odoo=0  odoo.com=0  odoocdn=0
  块1 手机横幅(odoo-mobile.png)        present=False
  块1 手机横幅(alt="Odoo移动端")        present=False
  块2 KPI /odoo/action- 链接          present=False
  块3 tips 渲染内容(tip_title)         present=False
  块4 preferences /odoo/digest        present=False
  任意 www.odoo.com                   present=False
  任意 odoocdn                        present=False
  /odoo/ 任意                         present=False   ← 最强的一条
```

对照 t32 复评时同一口径的 **len=34052 / odoo=20 / odoo.com=1 / odoocdn=5** —— 四块全部消除，且 **`/odoo/` 在整封邮件里已不存在**。

**退订功能未被静默破坏**（t31 当年就特意保过，本轮仍然在）：
`/digest/1/unsubscribe?token=cc8dfa92…&user_id=2` 实测存在。

### t44-AC2：按模板分别构造忠实上下文 + 写入「探针上下文必须与真实发送路径一致」注释 → ✅ 通过

- 代码：`scripts/check_odoo_trace.py:283+` 新增 `_digest_values(digest)`，docstring 明确写下 t44 的教训
  （「**探针上下文必须与真实发送路径一致，否则是假绿** —— t44 的教训：早先探针缺 kpi_data / tips /
  display_mobile_banner，渲染约 3.6KB 判全绿；忠实上下文里却有 20 处 odoo…」）。**我 t32 提的 F2 要求被逐字落实。**
- **根因也追到了最深层**：`digest.py:352-364` 的两条 preferences **只对 `base.group_erp_manager` 渲染**，
  普通用户构造的探针该区块整块消失 → 探针绿而忠实渲染红。代码里已用 `env.ref('base.group_erp_manager')` 构造。
- **同构性实测（本轮核心判据）**：
  | 来源 | digest 渲染长度 | odoo | odoo.com | odoocdn |
  |---|---|---|---|---|
  | 门禁 `--mail` 探针 | **28358** | 0 | 0 | 0 |
  | 我自己的忠实渲染 | **28359** | 0 | 0 | 0 |
  → **相差 1 字节**（token/日期长度差异），可判定探针已与真实发送路径同构。
- **渲染字节数已作为审计信号打印**：4 支模板每行都输出 `len=… odoo=… odoo.com=… odoocdn=…`，
  摘要那条是 `len=28358`（旧探针是 3662，一眼可辨）。

## 2. 队长点名核对的 5 项

| # | 项 | 结果 |
|---|---|---|
| 1 | 自己用忠实上下文实渲染（不用 `--mail` 绿作判据） | ✅ 已做，见 §1；并额外核对**探针也同构** |
| 2 | 逐块核对四块：横幅 / KPI `/odoo/action-` / tips / preferences | ✅ 四块 `present=False`，`/odoo/` 全文为 0 |
| 3 | 字节数演进与计数 | ✅ 终态实测 **28358（探针）/28359（忠实）**；计数 0/0/0。**说明**：历史值 24453→28603 我无法独立复现（属实现者的过程测量），仅确认终态 |
| 4 | 命中口径是否已含 `odoocdn` | ✅ 已含：计数逻辑 `low.count('odoocdn')`（:337），4 行输出均带 `odoocdn=…`，HIT 判定也纳入 |
| 5 | `digest_section_mobile` core arch 残留 | ✅ 按队长裁定以**可达性口径**处理：core 文件只读、不归零；该 section 未进入本次邮件渲染，**不据此判失败** |

## 3. 附带核实（不属于 t44 判定范围，但顺手验了）

- **t49（digest.tip 数据层清空）**：`digest.tip` 共 18 条记录，**含品牌词的 0 条**；
  渲染出的 tips 块也确已不出现（`tip_title` present=False）。t49 的 inScope 正是
  `brand_debrand_data.xml`，与 t44 无文件冲突。
- **全量门禁**：`check_odoo_trace.py` → **exit 0**「PASS：Odoo / 基座品牌痕迹 0 命中
  （公开站 24 + 4 角色 27 + 后台 1 = 52 条静态路由，另含动态发现）」，邮件面 4/4 覆盖 0 未覆盖；
  `check_english.py` → **exit 0**，5 角色全登录成功（0 条「登录失败，未扫描」），must-fix 0 / brand 0。

## 4. 超出 inScope 的文件

| 文件 | 归属 | 判定 |
|---|---|---|
| `custom_addons/edu_brand/views/odoo_debrand.xml`（+49） | t44 inScope | ✅ |
| `scripts/check_odoo_trace.py`（+113/-18） | t44 inScope | ✅ |
| `custom_addons/edu_brand/data_brand/brand_debrand_data.xml`（+120） | **t49 的 inScope**（文件内注释即写明 `digest.tip 数据层清空（t49）`） | ✅ 不计入 t44 |

→ **t44 无越界改动**。工作区其余改动（`edu_schedule/models/session_ext.py`、`docs/`、`tests/smoke/*`）
属其他任务，不能归因 t44。

## 5. 复评限制

1. 历史字节数（24453 / 28603）与「修前探针 HIT x1」的对照，**我无法独立复现**（那是实现者在时间轴上的测量），
   仅确认终态；不过终态是我自己渲染出来的，不影响结论。
2. 探针与忠实渲染的 1 字节差异未逐字节溯源（推测为 unsubscribe token 或日期格式长度）；不影响「同构」判定。
3. 我未修改任何被测文件。
4. 全部在本地 `edu19`；**生产未验证**。
