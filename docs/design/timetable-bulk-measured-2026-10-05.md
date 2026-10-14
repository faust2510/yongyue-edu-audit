# 周期排课重设计 —— 第 3 步「搬走停用」实测（2026-10-05）

> 依据 `docs/design/timetable-bulk-SYNTHESIS.md` §五 执行顺序第 3 步。
> 量具：`scripts/measure_timetable_bulk.py` 的**同一口径**（小灰字只数**叶子**节点）。
> **改前改后同一把尺子**，否则两列不可比。

## 做了什么

「批量停用」卡片（§18-B，17 行表 + 说明）**只在 `?tool=deactivate` 时渲染**，默认视图只留一行次级入口。

- **服务端分流**（不是客户端 Tab）：客户端 Tab 仍把 17 行表留在 DOM 里，窄屏那 4113px（整页 7168px 的 57%）照样要滚 ——
  搬走 DOM 才叫搬走。三份独立设计（A/B/C）都要求「停用必须离开默认视图」，此处取 C 的方案（**控制器 +2 行**，不新增菜单）。
- 改动面：`controllers/main.py`（`_render_bulk` 注入 `tool` 默认值 + 路由透传 `?tool=`）、`views/templates.xml`（卡片包进 `t-if` + 默认视图加次级入口）。

## 实测（1440×1000，`backoffice@local`）

| 指标 | 改前（默认视图） | **改后（默认视图）** | 工具页 `?tool=deactivate` |
|---|---|---|---|
| 整页高度 | 2290 px | **1568 px**（−31.5%） | 2311 px |
| 小灰字（叶子口径） | **75** | **21**（**−72%**） | 75 |
| 「批量停用」卡 | 在 | **不在** | **在** |
| 次级入口链接 | — | **在** | 不在（已在其中） |
| 主操作（「预览」）距顶 | 1220 px | 1241 px | 1241 px |

**设计文档当时的预测是「单这一刀 ⇒ −70% 灰字、−33% 页高」，实测 −72% / −31.5% —— 预测站住了。**

## 还没做（第 4、5 步）

- 主操作仍在 **1241px**（目标 ≤1000px 且在首屏）⇒ 第 4 步做 A 的骨架（两列字段 + 星期几 chip + 高级项 `▶` 折叠 + 顶部进度 + sticky 动作条）；
- **必取 C 的「还没查」诚实块**（右栏永远不许出现「无冲突」）；
- 用同一把尺子再复测一次 + 跑全量门禁 + 部署。

## 顺带修掉的一个环境坑（不是产品代码）

本地 `safe_upgrade.sh` 是**在正在运行的 web 容器里 `docker compose exec`** 跑升级的 ⇒
同一个容器里会有**两个 Odoo 进程共用一个库**，与容器自带的 cron 线程撞在 `ir_cron` 上：

```
ERROR odoo.sql_db: bad query: SELECT "ir_cron"."id" … FOR NO KEY UPDATE SKIP LOCKED
ERROR: could not serialize access due to concurrent update
⇒ registry 加载失败 ⇒ 报出的却是 ParseError: …/edu_schedule/data/cron.xml:7（**假线索**）
```

**这是偶发的**（cron 每 5 分钟一次），报错信息把人往 `cron.xml` 上带，实际与它无关。
确定性做法：**升级前 `docker stop <web>`，升级后再 `docker start`**，即可稳定通过。