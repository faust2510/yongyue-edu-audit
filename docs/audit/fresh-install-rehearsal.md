# 全新库「整装演练」——按 `deploy_myedu.sh` 的真实清单（2026-10-04 第 67 轮）

> 第 66 轮已把 `-i edu_life` 这条链修通；本轮按**部署脚本真正的清单**再走一遍。
> 结论：**第一趟（7 个模块）全绿；第二趟（`edu_nav`）在全新库上会崩**，且成因是**生成器把库内数字 id 写死**。

## 命令（可原样复跑）

```
create database edu19_fresh2;
# 第一趟：deploy_myedu.sh:156 的默认清单
odoo -d edu19_fresh2 --without-demo=all --stop-after-init \
  -i edu_life,edu_schedule,edu_apply,edu_portal,edu_brand,edu_tg_bind,edu_assess
# 第二趟：脚本第 3 步要求 edu_nav **单独跑**（不能与别的模块同一个 -u 列表）
odoo -d edu19_fresh2 --without-demo=all --stop-after-init -i edu_nav
```

## 第一趟：✅ 七个模块全部 `installed`

```
edu_apply installed ｜ edu_assess installed ｜ edu_brand installed ｜ edu_life installed
edu_portal installed ｜ edu_schedule installed ｜ edu_tg_bind installed
```

只有告警（`@class` 视图写法提醒 ×3、一处数据里的 Python 表达式缩进告警），**没有错误**。

## 第二趟：❌ `edu_nav` 崩在一条硬编码的分组 id 上

```
ERROR: bad query: INSERT INTO "ir_ui_menu_group_rel" ("menu_id","gid") VALUES (308, 87)
ERROR: violates foreign key constraint "ir_ui_menu_group_rel_gid_fkey"
CRITICAL: Failed to initialize database edu19_fresh2
```

### 成因（两条，都是「按库内数字 id 寻址」）

1. **`edu_nav` 的 depends 只有 `base`** —— 而它的数据要往**别的模块的菜单**上写 `group_ids`：
   崩的那条是菜单 **308 = `openeducat_classroom` 的 “Class Room Management”** ✗；
   2. 数据文件里 `group_ids` 用了**写死的数字 id**：`[4]` × **128** 处，另有 **1 处 `[51, 52, 87]`** ——
   其中 **87 = `edu_portal` 的「后台·完整视图」**。这些 id 是**生成时那个库**的 id，
   换一个库（尤其全新库）**根本对不上** ⇒ 外键直接违约。

### 为什么不能「顺手手改那一行」

`docs/code-map.md:110` 规定：`edu_nav` 的 data **由 `scripts/gen_menu_data.py` 从 plan JSON 生成、禁止手改**。
⇒ 真要修，得改**生成器**（让它按 **xmlid** 而不是数字 id 落盘），不是改产物。
本轮**没有改**，只登记（并已确认那份文件属「他人工作区」的既有约定：见 `study-scheduling-design.md:52`）。

## 一条要紧的上下文：**生产可能根本不装 `edu_nav`**

`docs/plans/major-track-elective-design.md:548` 实测记录写着「**生产未装 `edu_nav`**」。
而 `deploy_myedu.sh` 的默认 `-u` 清单（第 156 行）也**不含**它，脚本第 3 步才单独跑一趟。
⇒ 这条崩溃**只影响「有人在全新库上装 edu_nav」**，不影响现在这条部署链的主路径。
**但它是一个真问题**：要么把 `edu_nav` 修成可移植（改生成器），要么明确它**只在本地/一次性使用**，
并在部署文档里写清「新库不要装它」。**这个口径需要拍板**（见下方「待定」）。

## 另一处：三个必须 `-i` 的模块不在默认清单里

`deploy_myedu.sh:162-163` 的注释自己写着：「2026-09-14 补上 `edu_zh` 与 `edu_public` —— 原先漏同步…
**`edu_zh` 是新模块，远端首次要 `-i`（不是 `-u`）**」。演练实测：这三个**没被装上**：

```
edu_public uninstalled ｜ edu_zh uninstalled ｜ edu_quiz uninstalled
```

⇒ 新服务器首次部署时，**必须显式 `-i edu_public,edu_zh`（外加 `edu_quiz`）**，
不能只跑默认那条 `-u` 清单。建议把这一条写进部署前置清单（本轮只登记，未改脚本 ——
脚本属他人工作区，且改它要连同 `check_prod_menus.py` 的模块清单一起动）。

## 待定（需拍板）

1. **`edu_nav` 在全新库/新服务器上到底装不装？** 装 ⇒ 要改生成器按 xmlid 落盘；不装 ⇒ 在部署文档写明。
2. 新服务器首次部署的 `-i` 清单是否补上 `edu_public,edu_zh,edu_quiz`（以及 `edu_nav` 的取舍）？