# task-15：判据 C（表头折行）修复 —— /my/checkin/board 与 /my/points/me

> 2026-10-02 本机栈实测（`http://localhost:8069`，`db=edu19`）；375×812 与 1440×900 两档；
> `/my/checkin/board` 用 faculty、`/my/points/me` 用 student 登录。截图：[before/](before) vs [after/](after)。

## 0. 结论：六条验收逐条读数

| # | 验收 | 读数 |
|---|---|---|
| ① | `find_squeezed_tables.py` → OK | 改前：`/my/checkin/board` **表头折行×7**、`/my/points/me` **×3**（都 SQUEEZED）；改后 **4/4 RESULT=OK**（2 页 × 2 轮） |
| ② | 1440 下 thead computed display 仍 `table-header-group` | 两页均 **`table-header-group`**（改前改后一致 ⇒ 桌面一字未变） |
| ③ | 375 横向溢出 ≤8px | 两页 **`overflow=0px`**（改前也是 0 —— 本条缺陷不是整页溢出，是「装得下但被压窄」，判据 A 看不见） |
| ④ | 改前/改后 375 截图 | [before/](before) 与 [after/](after) 各 2 张手机图 + 2 张桌面图；人眼确认表头不再竖排、每行变成「标签左灰 / 值右对齐」卡片 |
| ⑤ | `safe_upgrade.sh` EXIT=0 | `bash scripts/safe_upgrade.sh edu_portal` → **EXIT=0**，失败特征 **0 条**（日志 `/tmp/edu19_upgrade.20261002-214028.log`） |
| ⑥ | 四个静态检查 | `check_view_xpath` / `check_md_tables` / `check_docs_index` / `check_po_sanity` → **全部 RESULT=OK、exit=0** |

## 1. 逐页 before → after（375 视口）

| 页面（角色） | 改前 | 改后 |
|---|---|---|
| `/my/checkin/board`（faculty） | 8 列，表宽 **345 = 容器 345**（判据 A 看不见），**7 个表头折行**（周几 + 日期两行被压得更窄） ⇒ SQUEEZED | **`thead=none`**（卡片），`edu-card-table` ✓，`td[data-label]`×56 |
| `/my/points/me`（student） | 5 列，**345 = 345**，**3 个表头折行**（「操作人」等） ⇒ SQUEEZED | **`thead=none`**，卡片 ✓，data-label×10 |

## 2. 改了什么（`custom_addons/edu_portal/views/welfare.xml` 一个文件）

- `edu_welfare_points_me`：表前 `<t t-call="edu_portal.edu_narrow_table_cards"/>` + 表加 `edu-card-table` + 5 个 td 各补 `data-label`（时间/分值/原因/操作人/备注）。
- `edu_welfare_board`：同样三步；**动态列（7 天）**的列名用 cell 自带的日期算出来：

```xml
<td t-foreach="row['cells']" t-as="cell" class="text-center"
    t-att-data-label="['周一','周二','周三','周四','周五','周六','周日'][cell['d'].weekday()] + ' ' + cell['d'].strftime('%m-%d')">
```

  为什么这么写：控制器（`controllers/welfare.py` 的 `board()`）只把日期与星期名 zip 成 `days` 传进来，
  **没有**给每个 cell 配列名，而控制器不在本卡写作用域 ⇒ 在模板里从 `cell['d']` 现算（周几 = 字面量元组按 `weekday()` 取，日期 = `strftime`）。
  渲染后实测标签形如 `周一 09-28`；页面 HTTP 200、无 QWeb 报错（见 §0 ⑤ 的升级日志与下面的可打开性检查）。

```
faculty  /my/checkin/board  HTTP=200  含「打卡看板」=True  字节=47357
student  /my/points/me      HTTP=200  含「我的积分」=True  字节=39521
```

没有新造样式、没改栅格/文案；媒体查询之外零规则 ⇒ 桌面端 DOM 与观感不变（§0 ② 是机械证明）。

## 3. 这条判据的价值（为什么值得单独修）

这两张表**宽度上完全「合规」**：表宽 = 容器宽 = 345，文档溢出 0 —— 判据 A（表宽 > 容器宽）与四轴 UI 门禁都绿。
但列被自动布局压窄后，2~3 字的中文表头只能竖排成两行，读起来是「得分/满分」上下叠着。
**「没有溢出」不等于「能读」** —— 这正是队长本轮补判据 C（折行表头 ≥2）的意义；本条与 task-12 的判据 A 互补。

## 4. 复跑命令

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy \
  no_proxy=127.0.0.1,localhost /opt/homebrew/bin/python3 \
  scripts/find_squeezed_tables.py --path /my/checkin/board --role faculty
#   /my/points/me --role student

# 截图 + 逐表读数（375 与 1440，含 thead display / 表宽 / 容器宽 / data-label 计数 / 页面溢出）
/opt/homebrew/bin/python3 docs/audit/narrow-tables-c/shots.py docs/audit/narrow-tables-c/task15/after \
  --target=/my/checkin/board:faculty:board --target=/my/points/me:student:points_me
```
