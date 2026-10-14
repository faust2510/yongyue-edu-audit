# v3 门禁三件套（t3 交付）

> 目的：在 v3 实现开工前先造好「尺子」。工具都是**只读**的（GET / 截图），不改业务代码，也不写库。
>
> **基线状态**：
> - ❌ **作废：2026-09-12 12:28–12:29 那份**（在配置损坏窗口内取样：`list_db=False` 且无 `db_name`、容器 12:32 重启），仅作历史记录保留。
> - ✅ **有效基线：2026-09-12 12:48 起**（`config/odoo.conf` 已修为 `db_name = edu19` + `list_db = False`，取样前通过三步探活），数值见 §6。
>
> 复测前必须做下面的**三步探活**。
>
> **根因（队长 2026-09-12 更正版）**：全站 404 的主因是「**多库 + 没有默认库**」→ 请求落进
> `request._serve_nodb()`；`list_db` 只决定是否暴露库列表/选择器，是帮凶不是主犯。
> **实际修复 = `config/odoo.conf` 加 `db_name = edu19`**，`list_db = False` 是刻意保留（与生产一致），
> **不要改回 True**。db_name 生效后，**不带 `?db=edu19` 的裸 URL 也正常了**。
>
> 仍然要记住的陷阱：**裸 curl 不带 cookie jar 时 `/web/login?db=edu19` 会 302 回自己**
> （Odoo 选库会话跳转，源码 `odoo/http.py` 的 `session.db = dbname`），那不是死循环 ——
> `requests.Session` 或 `curl -c/-b jar` 即可。
> 另外实测修正：**`/web/database/selector` 在 `list_db=False` 下仍返回 200**
> （内部 `db_list(force=True)` 绕过开关，只是列表受限），所以「关闭数据库选择器」的说法不准确。

## 0. 跑门禁前的三步探活（永久纪律）

```bash
# 1) 无升级锁（有人的 safe_upgrade.sh 在跑就别开测）
ls "${TMPDIR:-/tmp}/edu19_upgrade.lock" 2>/dev/null && echo "有升级在跑，停" || echo "无锁 OK"
# 2) 容器不是刚重启（Up < 30s 不跑）
docker compose ps --format '{{.Name}} {{.Status}}' | grep web-1
# 3) 探活：**带 cookie jar**（无 jar 会看到自跳 302，被误判为故障）
J=/tmp/cj; rm -f $J
curl -s -c $J -b $J -o /dev/null -w '%{http_code}\n' 'http://localhost:8069/web/login?db=edu19'   # 期望 200/302/303
curl -s -c $J -b $J -o /dev/null -w '%{http_code}\n' 'http://localhost:8069/login?db=edu19'       # 期望 200，严禁 404
```

> **检查器退出码语义（2026-09-12 定契约，详见 `docs/dev-workflow.md`）**：`0=OK`｜`1=FAIL`｜`2=ENV`｜`3=INCOMPLETE`；
> **只有 `FAIL(1)` 应阻断流程**，`ENV(2)` 与 `INCOMPLETE(3)` 只提示不阻断（`--strict` 可把 3 归为 1）。
> 因此：看到静态检查报 `RESULT=INCOMPLETE` 而升级照常进行 —— **那是设计如此，不是异常**；
> 同理 `safe_upgrade` 曾因"非零即拒"两次挡死全队升级，已按退出码分级修好。

任一条不满足 → **不要跑门禁**（跑了也是假红）。矩阵脚本已把「无锁 + Up>30s + 带 cookie 探活」内建为
`health_check()`，不满足直接 `exit 2`；采样期间若发生容器重启，脚本把这类失败单列为 **ENV（环境）**、
不计入 FAIL，并在 ENV ≥10% 时判「样本作废」`exit 2`。

> **读数自证头（2026-09-12 定，引用任何门禁结论时一并贴出）**：
> `工具自证（REVISION · 指纹 · 断言 N 条）` + `MEASURED_AT=<时间>` + `容器 Up=<秒>` + `退出码`。
> 理由：本轮出过「旧快照往返」「指纹过期」「他人 N/N 全绿不知是哪一版」三类事故 ——
> **不绑版本与时间的数字，等于没测**。工具侧自证见 `check_english --selftest` / `check_view_xpath --selftest` / `check_odoo_trace --selftest`。
> 采样稳定窗口的正确姿势（已脚本化验证）：等「无锁 + 容器 Up>60s」→ 跑门禁 → **事后比对
> `docker inspect -f '{{.State.StartedAt}}'` 前后一致**才算 `SAMPLE_VALID`；不一致就重跑，
> 不要拿重启窗口里的数字当基线。

| 工具 | 一句话 | 退出码 |
|---|---|---|
| `tests/smoke/ux_v3_route_matrix.py` | 100 路由 × 5 角色 = 500 检查点的可达性与 5xx/Traceback 门禁 | 0=无 FAIL，1=有 FAIL，2=环境不可用（登录失败/服务 5xx） |
| `scripts/check_english.py` | 可见英文门禁：文本节点 + placeholder/title/aria-label/alt，按匿名 + 四角色各扫一遍 | 0=零残留，2=有残留，1=运行错误 |
| `scripts/shoot_ux_v3.py` | 4 角色 × 3 视口截图 + 每页 DOM 高度（首页瘦身指标 M3） | 0=全部 200，1=有页面未达 200 |
| `tests/smoke/zero_loss_reachability.py` | 零功能丢失：L1 路由可达（35 张旧卡 + 9 张动态卡）+ L2 IA 覆盖（35 条 href 必须出现在 `/my/apps`）+ L0 共享类契约 | 0=全绿，1=有缺失，2=运行错误（含 `/my/apps` 未交付） |
| `tests/smoke/data_driven_brand_leak.py` | **数据驱动的品牌泄漏**（t9 固定检查项）：技术账号建的数据渲染到「上传人/操作人」列时不得泄漏基座品牌；自带造样本与清场 | 0=通过，1=发现泄漏，2=运行错误 |
| `tests/smoke/audit_completeness_smoke.py` | **审计完整性**（门禁测不到的业务正确性面）：后台/模型边界直写 + 门户三条路径（页面保存 HTTP／导入／上期复制）各自必须留痕且字段正确；每例还原 + `leftover=0`；连跑两遍一致 | 0=全绿，1=有断言失败，2=环境不可用/无夹具 |

**为什么有这条**：t9 的七项测的是**可观测面**（路由/英文/品牌/高度），**审计完整性测不出来** ——
"改分是否留痕"只能靠**行为级验证**（写一次 → 查留痕表 → 字段对）。t13-F1 的教训就是
"claim（唯一入口、全部留痕）≠ 证据"。`audit_completeness_smoke.py` 把这条证据固定下来：
四类写入路径 × 正向断言（防"恰好没数据所以恰好通过"）× 还原清场 × 连跑两遍。

**第 4 步（2026-09-12 加）：目标页不是 5xx —— 区分「环境」与「真回归」**

两者的表现很像，判据必须分开：

| | 环境问题（ENV） | 真回归（FAIL） |
|---|---|---|
| 症状 | `ConnectionError: Remote end closed connection`、登录失败、整站瞬态 5xx | 页面 5xx 而其它页正常；日志有 Traceback |
| 门禁表现 | 矩阵单列 **ENV**、不计 FAIL；ENV ≥10% → 「样本作废」exit 2 | 矩阵记 **FAIL** + 打印服务端错误标记 |
| 动作 | 等 60s 复跑，**不要**当回归上报 | 查 `docker compose logs web --tail 40`，尤其 `grep "does not exist"`（字段在码不在库 = 漏 `-u`），定位到根因再报 owner |
| t9 流程 | 门禁前轮询 `/web/login?db=edu19` 得 200/302/303 再开跑；命中 ENV 就复跑 | 命中 FAIL 就停下来定位，不许「重跑一次看看」掩盖 |

> 实战教训：13:10 的 `/my/calendar` 全角色 500 一开始被当成「又是环境抖动」，实际是
> `op_subject.credit_points` 列缺失（代码加了字段没 `-u`）——见 §7.4。**真回归必须定位到根因。**

**第 5 步（2026-09-26 加）：探活/前置检查不许被 `except: pass` 包住 —— 「永远绿的死代码」**

判据纪律，不只是代码 bug：**被宽 except 吞掉的前置检查 = 从未生效，而且它永远报"通过"**。
本轮实例（B 组交付时查获）：`ux_v3_route_matrix.py: health_check()` 第 2 步「容器不是刚重启」
用了 `re.search(r'Up (\d+) seconds', …)`，而该脚本**从未 `import re`** ⇒ 每次抛 `NameError`
被同一函数的 `except Exception: pass` 吞掉 ⇒ **这一整步从未执行**，「三步探活」实际只有两步。
修法：加模块级 `import re`（已随本轮切换落地）。同类先例：`set -e` 下 `python3 …` 紧跟 `rc=$?`
也是死代码 —— 判据同一条：**要断言"检查过"，就必须让"检查失败"能改变结论**（抛出/计数/非零退出皆可，
但不能是 pass）。

> 姊妹教训（同一轮，自证机制的反面用法）：把探名单局部变量命名为 `probe`，**遮蔽了模块级函数
> `probe()`** ⇒ 实跑 `TypeError: 'list' object is not callable`。**门禁自身也要能崩给你看**：
> 实跑一次（而不是只 import 一次）比任何静态自检都值钱。

> 名单来源变更（2026-09-26，B 组）：三个 UI 门禁（`ux_v3_route_matrix` / `check_accessibility` /
> `check_english`）的**路由名单改为从 `tests/ui/surface.json` 读**（`gates` 含自己名字的条目），
> 脚本里的常量降级为「扫描口径」；表读不到 ⇒ **exit 3=INCOMPLETE**（不判 FAIL、不退回写死名单）。
> 表内缺登记的核心路由（历史案例：`/` —— Odoo website 核心渲染，不在 `custom_addons` 的
> `@http.route`）由各脚本的 `SURFACE_MISSING` 逐条补偿，**每次运行都点名打印**；补进表后撤掉补偿。
>
> **2026-09-28（B 组）现状：三张门禁的 `SURFACE_MISSING` 都已删空。** `/` 已登记进表
> （`key=root`，`gates` 含三张门禁），删补偿后逐脚本实测覆盖没变小：矩阵执行集仍是
> **98 条 = 常规探 96 + 强断言壳 2**、`/` 改由表行进入探名单（真机 exit 0、480/480 PASS）；
> `check_accessibility --list` 仍是 28 页取样 / 去重 22 路径（guest `/` 照扫）；
> `check_english --list` 仍是 85 条路径 × 角色（guest `/` 照扫）；三者对账均为
> 「执行集 − 表 = 空 ｜ 表 − 执行集 = 空」。留**空** dict 是为了保住这处
> 「表里缺登记时必须显式写理由」的落点 —— 少扫几页 = 假绿，不许静默。

### 0.0.1 三张门禁的执行集对齐（2026-09-28，B 组复核；表指纹 921c3dc6 → **8ae6af66**）

**口径（三者同一套）**：脚本各自读 `tests/ui/surface.json`，只取 `gates` 含自己名字的行 ——
「该跑哪些页」不再来自脚本自己的常量（那些常量只降级为「用哪个身份扫」的取样口径）。
逐脚本的**执行集 vs 表**对账每次运行都打印，本轮三个都是双向空集：

| 门禁 | 表登记 | 真跑 | 对账（执行集−表 ｜ 表−执行集） | 备注 |
|---|---|---|---|---|
| route_matrix | **101**（10:47 前为 98） | **101** = 常规探 99 + 强断言壳 2（10:47 前为 98 = 96 + 2） | 空 ｜ 空 | 另 3 条 REDIRECT_STRICT + 4 条按角色强断言（`/my/apps`），与常规探不重复计数 |
| accessibility | 22 | 22 路径 / 28 页取样 | 空 ｜ 空 | 取样 = 身份×路径（口径 AUDIT_ROUTES） |
| english | 85 | 85 路径 × 角色 | 空 ｜ 空 | guest 21 / student 69 / faculty 85 / parent 69 / backoffice 85 |

并集 102 行；**只有 21 行被三张门禁同时覆盖**，其余 **81 行**至少缺一张。下表是这 81 行的
**成员差异（登记口径差异，不是执行差异 —— 每张门禁执行的东西都和表逐条相等）**分类：

| 类别 | 行数 | 例 | 为什么不一样 |
|---|---|---|---|
| rm+eng，无 axe | **63**（10:47 前为 60） | `/my/home`、`/leave/approvals`… | axe 取样口径只有 28 页（一页一个代表身份），这些页不在样本里。**+3 = 10:47 补进来的 `/assess`、`/assess/my`、`/assess/review`**（它们从「仅 eng」类移到这里，见下） |
| 仅 rm | 17 | `/my/checkin*`、`/my/evaluation*`… | 14 页不在 axe 样本、也不在 english 口径名单里 ⇒ **只有 HTTP 层覆盖**（要扩样本属口径变更）；另 3 条是 `kind=endpoint`（`/downloads/manage`、`/my/checkin/export`、`/my/checkins/export`）—— 同类端点里表确实登记过 acc/eng（`/downloads`、`/downloads/mine`、`/downloads/stats`），所以这**不是按 kind 一刀切**，而是历史口径的分配差异 |
| ~~仅 eng~~ | ~~3~~ → **0** | ~~`/assess`、`/assess/my`、`/assess/review`~~ | **已消除（2026-09-28 10:47，队长裁定一，B 组执行）**：这三页此前只有 english ⇒ **没有任何 HTTP 层门禁**。给它们补 `route_matrix` 后，实测执行集 **98 → 101**、检查点 **480 → 495**、对账双向空、**exit 0（PASS 495 / WARN 0 / FAIL 0 / ENV 0）**；对 `roles` 内的身份**全部直接 200**：`/assess` = stu/fac/bo/admin，`/assess/my` = stu，`/assess/review` = fac/bo/admin（其余身份 303→`/my/home` 后 200，不在期望集内 ⇒ 不判 200）。三条没有一条落到 FAIL/非 200，故**未回撤** |
| acc+eng，无 rm | 1 | `/register` | 只有匿名能到它（登录身份一律 303→`/my/home`），而矩阵**没有匿名会话** ⇒ 加 `route_matrix` 只能拿到 5 个登录身份被弹走的读数，是假覆盖；要真覆盖得给矩阵加匿名探测口径 |

**护栏实测（防「静默缩小覆盖」复发）**：`ux_v3_route_matrix.py --surface /tmp/does-not-exist.json`
⇒ **exit 3（INCOMPLETE）**，明说「名单没有来源」，**不退回写死名单**；生成器侧
`ui_surface_report.py` 的 `load_gates()` 对形态 B 门禁是**从表读回**登记集
（对账实测 route_matrix = 101，与表逐条相等，不是脚本里的残留字面量 —— 那正是 97→7 事故的成因）。

> **口径变更记录（2026-09-28 10:47，队长裁定一，B 组执行）**
> 事由：`/assess`、`/assess/my`、`/assess/review` 三页当时**只有 `english`** ⇒ 没有任何 HTTP 层门禁。
> 动作：在 `tests/ui/surface.json` 给这三行 `gates` **只加** `route_matrix`（**只动这一个字段**，roles/kind/scope/status 一字未改；表指纹 `921c3dc6 → 8ae6af66`）。
> 实测（`python3 tests/smoke/ux_v3_route_matrix.py`）：执行集 **98 → 101**（常规探 96 → 99）、检查点 **480 → 495**、
> 对账**双向空集**、**exit 0**（PASS 495 / WARN 0 / PENDING 0 / FAIL 0 / ENV 0）。
> 逐角色读数（`/tmp/rm_assess.json` 可复算）：`/assess` expect={admin,bo,fac,stu} 全部**直接 200**；
> `/assess/my` expect={stu} → stu 直接 200（fac/par/bo/admin 303→`/my/home` 后 200，不在期望集）；
> `/assess/review` expect={admin,bo,fac} 全部**直接 200**（stu/par 303→`/my/home` 后 200）。
> **没有任何一条角色不是 200 ⇒ 未回撤任何一行。**
> 连带：本节的「仅 eng」类由 **3 行 → 0 行**，这 3 行改记入「rm+eng，无 axe」（60 → 63）；并集仍是 102 行、三张全跑仍是 21 行。
> 相邻不变：`check_ui_surface` exit 0（有门禁页仍 102）｜`accessibility --list` 仍 28 页/22 路径｜`english --list` 仍 85 路径 × 角色｜`ui_surface_report` 核对 0 + 自证 0。
> **本轮不动**（队长裁定三）：`/register`（acc+eng 无 rm）与那 17 行「仅 rm」—— 要动的是**取样口径**（给矩阵加匿名会话 / 给 axe 扩样本），需用户拍板。

## 0.1 解释器：跑 Playwright 类门禁必须写全路径（2026-09-28 加，D 组复核时实测）

**症状**：裸 `python3 scripts/check_ui_usability.py --selftest` 报
`ModuleNotFoundError: No module named 'playwright'` ⇒ 很容易误判成「门禁坏了 / 依赖没装」，
实际是**解释器选错**：本机**同一个 `python3` 在不同 shell 下解析到不同解释器**。

| 解析方式 | 结果 | 版本 | playwright |
|---|---|---|---|
| `bash -lc 'which python3'` | `/usr/bin/python3` | 3.9.6 | ✗ 没有 |
| `zsh  -lc 'which python3'` | `/opt/homebrew/bin/python3` | 3.14.6 | ✓ 有 |

（`python3 -V` 的实测输出：bash 登录壳 = `Python 3.9.6`，zsh 登录壳 = `Python 3.14.6`。
所以「默认 python3 能不能跑」**取决于你用哪个 shell**，与脚本无关。）

**纪律**：凡 import playwright 的门禁，**一律写全路径**，优先

    /opt/homebrew/bin/python3            # 3.14.6（体检组实测跑通，首选）
    /Users/qwe/miniconda3/bin/python3    # 3.13.13（备选，同样 import 得到 playwright）

    /opt/homebrew/bin/python3 scripts/check_ui_usability.py --selftest
    /opt/homebrew/bin/python3 tests/smoke/ux_v3_route_matrix.py --role stu --role fac --role par --role bo

**不 import playwright 的门禁**（`check_english.py` / `check_odoo_trace.py` /
`check_qweb_dict_foreach.py` / `check_accessibility.py` / `check_ui_surface.py`）
用裸 `python3` 亦可，但要让读的人一眼看出是哪支解释器，仍建议写全路径。

> 同一份说明已写进 `scripts/check_ui_usability.py` 的 docstring（用法段之后）；
> 改了这里的口径请同步那一处。

---

## 1. 路由 × 角色矩阵

```bash
python3 tests/smoke/ux_v3_route_matrix.py            # 全量
python3 tests/smoke/ux_v3_route_matrix.py --role stu # 只跑学生（约 40 秒）
python3 tests/smoke/ux_v3_route_matrix.py --strict   # WARN 也算失败
python3 tests/smoke/ux_v3_route_matrix.py --json /tmp/m.json
```

覆盖：**100 条路由**（公开站 21 + 门户 54 + 教师/教务 21 + v3 新页 4）
× 角色 {stu, fac, par, bo, admin}（stu/fac/par/bo 密码 demo123，admin/admin）。

判定规则：

- **FAIL**：任一跳 5xx / 响应体含 `Traceback`、`Internal Server Error`、`odoo.exceptions.`，
  或该路由声明「本角色必须 200」而未拿到 200，或最终落地 4xx（404 例外见 PENDING/WARN）。
- **PENDING**：v3 待交付路由（`/login`、`/apps` 属 t4 brand-eng；`/my/apps`、`/my/study` 属 t6 study-eng）
  当前 404 —— 如实列出，不算失败；交付后把它们从 `PENDING_V3` 移出，矩阵会自动纳入断言。
- **WARN**：非预期 404、403、被弹回登录页。
- **PASS**：200（允许 3xx 跳转后 200）。
- 跑之前先探活（脚本内置）：`GET /web/login` 若 5xx 直接 `exit 2`，避免升级窗口里刷出一屏假红。

**干净基线（2026-09-12 12:29）**：检查点 500 → PASS 477 / WARN 3 / PENDING 20 / **FAIL 0**；MATRIX_EXIT=0。

- WARN ×3：`/my/checkin/board` 对 fac / bo / admin 返回 **404**。**定性（队长 2026-09-12 代码实证更正）**：
  这不是"设计上只给学生"，而是 **v2-B6「管理员打卡看板」的既有缺陷** —— `controllers/welfare.py:172-203`
  对 `group_user`（教师/教务/管理员）进入渲染分支后 `request.render("edu_portal.edu_welfare_board")`，
  而**该模板全仓不存在**（只有控制器这一处引用、零定义）→ 404。**非 v3 引入、不在本轮范围**；
  处置选项（新建看板模板 / 让该路由优雅重定向）已交用户决定。
- PENDING ×20：`/login`、`/apps`（t4）、`/my/apps`、`/my/study`（t6）× 5 角色。

## 2. check_english（文本 + 属性 + 四类分流，v3.1）

```bash
python3 scripts/check_english.py --selftest        # 自证：属性扫描 + 四类分流（不连服务），19 项全 PASS
python3 scripts/check_english.py                   # 匿名公开页 + 四角色全量
python3 scripts/check_english.py --role faculty --json /tmp/en.json
python3 scripts/check_english.py stu@local demo123 # 兼容旧用法（单账号）
```

- 扫描范围：`>文本<` 节点 **+ `placeholder` / `title` / `aria-label` / `alt`** 四类属性；
  先按区间剔除 `<script>` / `<style>` / 注释。
- **验收口径 = must-fix 命中数 0**（不再是「任意英文 = 0」）。四类分流：

| 类别 | 含义 | 处理 |
|---|---|---|
| **must-fix** | 我们模板里、用户或读屏可见、应当汉化的英文 | **门禁唯一失败条件**，必须清零 |
| whitelist | 品牌名 `COVENANT REFORMED SEMINARY`、品牌口号 `COVENANT · REFORMED · TRUTH`、第三方产品名 `Zoom` / `Telegram`、语言自称 `English` / 语言代码 `EN` | 保留 |
| data | 课程代码（`^[A-Z]{2,5}-[A-Z]{2,5}$`，如 CRS-MCS）、文件后缀（pdf/docx/xlsx…）、编号/邮箱/URL、**账号显示名 `Administrator`**（res.users 数据而非模板文案；是否改成中文由用户决定） | 不判失败 |
| theme | website 编辑器 navbar 区块（`<nav data-name="Navbar">`，含 `d-lg-none` 的移动端副本）内的命中 | 不在 custom_addons 内（基座只读）；要改需 edu_brand 覆写视图 |

- **每条 must-fix 都带「示例路由 + 来源文件:行号」**，可直接去改（脚本对 `custom_addons` 做子串匹配、**视图模板优先**；
  短词如 `EN`/`Home` 可能命中非唯一出处，改动前请打开文件确认）。
- `Main` / `Mobile` 的定性有实测证据：它们在 `<nav data-name="Navbar" class="... d-none d-lg-block / d-block d-lg-none">`
  区块里（桌面/移动端各一份，CSS 互斥显示），**custom_addons 全仓 grep 不到** —— 所以按「区块内命中」自动归 `theme`，
  而不是加白名单把一个词掩盖过去（白名单会掩盖真正的 Mobile 文案）。

**基线（2026-09-12，EN_EXIT=2）**

| 角色 | 路由数 | must-fix | whitelist | data | theme |
|---|---|---|---|---|---|
| guest（匿名） | 21 | 0 | 0 | 0 | 0 |
| student | 67 | 121 | 120 | 127 | 472 |
| faculty | 86 | 137 | 148 | 105 | 584 |
| parent | 67 | 117 | 114 | 69 | 448 |
| backoffice | 86 | 133 | 144 | 122 | 568 |
| **合计** | — | **508** | 526 | 423 | 2072 |

去重后 must-fix 共 **20 条**不同串，全是真问题（按命中数排序，含来源）：

| must-fix 串 | 次数 | 示例路由 | 来源（视图优先） |
|---|---|---|---|
| EN | 426 | /（语言切换控件） | `edu_brand/views/brand_templates.xml:20`、`edu_portal/views/edu_portal_templates.xml:48` |
| breadcrumb | 16 | /help/student | `edu_portal/views/help_center.xml:52`（另 `batch3.xml:94`、`edu_schedule/views/templates.xml:10`） |
| Notifications | 6 | /my/home | `edu_portal/views/batch2.xml:681`（另 :744） |
| Apply Now | 4 | / | `edu_brand/views/brand_templates.xml:37` |
| Academics | 4 | / | `edu_brand/views/brand_templates.xml:65` |
| Student Portal | 4 | / | `edu_brand/views/brand_templates.xml:119` |
| Public Information | 4 | / | `edu_brand/views/brand_templates.xml:138` |
| About Us | 4 | /about | `edu_brand/views/pages.xml:9` |
| Programs | 4 | /programs | `edu_brand/views/pages.xml:59` |
| Admissions | 4 | /admissions | `edu_brand/views/pages.xml:286` |
| Journal | 4 | /journal | `edu_brand/views/pages.xml:355` |
| Course | 4 | /courses-offered | `edu_portal/views/lms.xml:93` 等 |
| Home / Search library / Search anything... / Search / Open profile / Notifications / Contact / Add Your Skill | 4/4/2/2/2/2/2/1 | /my-library、/my/home、/student/profile | `batch3.xml:99`、`batch2.xml:742`、`batch3.xml:95` 等 |

（`EN` 那 426 次是语言切换控件在每页重复出现；改一处即可全站生效。）

已知盲区（写在这里以免被误读为「零残留」）：**含中英混排的字符串会被跳过**
（例如登录页 `<title>Login | 永约学坊</title>`），因为过滤器用「含 CJK 即视为中文文案」排除误报。
若要覆盖混排标题，需要单独一条规则（交给 t4 / i18n 决定）。

**已知陷阱（2026-09-12 修复，务必知道）**：跳过区间（`<script>`/`<style>`/注释/`<template>`）分批
拼接后**必须按起点排序**才能交给 `_inside()` —— 该函数"命中即停"的假设依赖有序区间。
排序前，**文档位置靠后的 `<script>` 会让位置靠前的 `<template>` 区间被漏判**，
后果是把模板/脚本里的英文当成**可见文案**（假阳性，方向与漏报相反）。
selftest 的「`<template name="Apply">` 里的 Apply 不应命中」断言正是为此设的：改坏排序它会立刻 FAIL。

**判据补充（队长 2026-09-12 定，t9/t14 必读）**

1. **`latest_version` 没变 ≠ 没升级**：Odoo 只在 manifest 版本号变化时才更新该字段
   （`edu_portal` 至今仍是 `19.0.1.11.0`，但已多次成功升级）。判断「列/视图有没有建出来」要用
   `information_schema`（列）或 `ir_ui_view`（视图），**不要看版本号**：
   ```bash
   docker compose exec -T db psql -U odoo -d edu19 -tAc "select count(*) from information_schema.columns where table_name='op_subject' and column_name='credit_points'"
   ```
2. **定性必须回渲染 HTML**：见下条同源陷阱。

**来源提示的启发式与两次误报修正（2026-09-12，flow-eng 报、verifier 复核）**

`来源: 文件:行号` 是启发式，**不是渲染路径证明**。两次真实误报及修正：

| 误报 | 现象 | 修正 |
|---|---|---|
| `txt` | 提示指向 `views/roles.xml:299`，那行其实是 CSS 类 `class="oe-norec-txt"` | 短英文串改**词边界**匹配（`(?<![-\w])…(?![-\w])`），并**排除 class/style/id/data-* 属性值内**的命中 |
| `OpenEducat Bot` | 提示指向 `controllers/roles.py:93` —— 那是 docstring 里的说明串（页面实际显示「系统」） | `.py` 文件**跟踪三引号块**并跳过 docstring、跳过 `#` 注释行 |

修正后自检：`OpenEducat Bot` → **无模板出处**（正确：它是 `res_users` 的**数据显示名**，不是模板文案）、
`breadcrumb`/`Add Your Skill` → 无出处（t17 已汉化，串已消失）、
`Course` → 只剩 `<template name=…>` 结构性出现（渲染标题已改「开设课程」）。

> 仍**必须**遵守的老规矩：**定性回渲染后的 HTML 上下文取证**。
> `Course` 曾被提示为 `lms.xml` 的 `<template name="Edu LMS Courses">`，
> 实际渲染源是 `<title>Course</title>`（队长据此误判过一次，我按渲染上下文纠正）。


## 2.1 两类门禁的分工与边界（t37 明确，2026-09-12）

| | `check_english.py` | `check_odoo_trace.py` |
|---|---|---|
| 目标 | **可见英文残留** + **可见文案里的品牌痕迹** | **Odoo/基座品牌痕迹**专项（含外链、数据不变量） |
| 扫什么 | 文本节点 + 4 类可见属性（`placeholder/title/aria-label/alt`） | 文本节点 + 外链（`href/action/src`）+ `meta generator` + **技术账号显示名（数据不变量）** + 属性提取（t26 后） |
| 不扫什么 | 技术属性（`class/style/id/data-*`）、`<script>/<style>/<template>`、编辑器 navbar 区块归 theme | 一般英文文案（那是 check_english 的活） |
| 命中分类 | `must-fix`（英文）／`brand`（**中英混排里的品牌 token**）／whitelist／data／theme | 单一口径：命中即 FAIL |
| 失败条件 | `must-fix > 0 或 brand > 0` | 命中 > 0 |

**边界（哪些是重叠、哪些是盲区，如实写）**：
1. **重叠（有意冗余）**：Odoo 品牌串若出现在**文本节点**，两个门禁都会报 —— 这是纵深，不是错误；修一处即可同时变绿。
2. **曾经的双盲区（已修，t26 + t37）**：`title="转到您的Odoo应用程序"` 这类**中英混排属性值**，
   t26 之前 check_odoo_trace 不扫属性、check_english 见 CJK 就跳过 → **两边都报 0**（§5.2 有完整分析）。
   现在 check_odoo_trace 扫属性、check_english 新增 `brand` 桶，两侧都能抓到。
3. **仍然的盲区（声明，不掩盖）**：
   - check_english **不扫** `value="…"`、`aria-describedby`、`data-*` 等非四类属性（按设计）；
   - check_english **跳过纯中文串**（按设计）——所以「中文串里混了品牌名」只由 `brand` 桶覆盖品牌 token，
     其它英文单词仍不报；
   - 两者都不扫**图片内文字**、PDF 内容、邮件模板渲染结果。
4. **判读口径**：任何「0 命中」结论**必须注明扫描口径 + 取样时间**（本轮第五种假绿就是"两个门禁盲区互补"造成的）。
5. **互补 ≠ 并集完备（study-eng 指出、队长升格为规矩）**：两个门禁合起来覆盖
   `文本节点 + title/placeholder/aria-label/alt(+content)`，但**将来若有可见文案走
   `aria-description`/`data-tooltip` 等别的属性，两者会同时漏**。
   因此 `check_english.py` 现在把"覆盖哪些位置/不覆盖哪些位置"写成**可审计声明**
   （docstring + `--coverage` + 每次汇总尾部原样打印），新增可见位置时必须先登记再扫描。
   **声明不是免责，而是把"隐含假设"变成"可核对的清单"。**



### 2.1.1 接缝判据（t48，2026-09-12）

`check_english` 与 `check_odoo_trace` 是**两个独立门禁**，各自的 `--selftest`
只证明"自己没坏"，**证不了接缝**。因此新增离线脚本 `tests/smoke/gate_seam_check.py`：

```
样本                                          期望              说明
(a) 纯英文属性 title="Notifications"            ≥1 报            **职责差异**：品牌门禁不管通用英文，别去"修"它
(b) 纯英文文本节点 Odoo                         ≥1 报
(c) CJK+品牌 token 属性 title="转到您的Odoo应用程序"  ≥1 报        2026-09-12 事故样本（曾两侧同时漏）
(d) CJK+品牌 token 文本节点                     ≥1 报
(e) 纯中文对照                                  **两个都不报**     对照组：判据强度的一半（防"什么都报"伪造绿）
(f) 未登记属性里的品牌 token data-tooltip="Odoo" **两个都不报**     known-gap（预期沉默，**非失败**）
```

判定与纪律：
- **断言不绑定具体工具**（只断言"至少一方报 / 两方都不报"）→ 任一方改了提取口径立刻红；
- **(f) 翻转是信号不是 bug**：若某门禁将来扩大了属性范围，(f) 会翻成"报" → 提示**覆盖声明已过期**，
  应同步更新 `check_english` docstring / 本节，并把 (f) 升格为正向样本；
- **二阶边界（写清楚免得被过度解读）**：本脚本直接喂两个**提取器**，只验证**提取 + 分类口径**；
  **路由/角色覆盖面不在射程内** —— 某条路由从清单漏掉它仍会全绿（那由 `--list-routes` 与矩阵脚本管）；
- **双向证据**：`--inject-fault historical-blindspot` 复现当日"双侧隐藏" → 脚本**必须变红**（已实测：样本 (c) 失去全部报告者）；
  `--inject-fault trace-attr` 单侧降级**不会红**，脚本会打印「另一门禁兜住 → 这正是重叠覆盖的价值」。
- 接入（由队长做）：与两个 `--selftest` 并列进 `docs/code-map.md` §10 第 0 步"离线自证族"。

## 3. 截图矩阵 + DOM 高度（M3）

```bash
python3 scripts/shoot_ux_v3.py                      # guest + 四角色 × 3 视口
python3 scripts/shoot_ux_v3.py --page home          # 只拍页名含 home 的页
python3 scripts/shoot_ux_v3.py --with-admin         # 追加 admin 后台页
```

- 产物：`tests/gap/shots/ux-v3/<role>/<width>/<page>.png`（全页截图，**63 张**）
  + `tests/gap/shots/ux-v3/heights.json`（每页 scrollHeight / body / viewport）。
  注意 `.gitignore` 里的 `shots/` 会忽略该目录 —— 截图是本地证据产物，不入库。
- 视口：1280×900 / 768×1024 / 375×812；角色：student / faculty / parent / backoffice（+ guest 公开站）。
- 登录一律走 `/web/login?db=edu19`，并兼容 t4 之后的 `/login` 别名。
  注意：不带 cookie 直接 `curl /web/login?db=edu19` 会 302 回自己（Odoo 选库跳转），
  这不是死循环 —— 用带 cookie jar 的会话（`requests.Session`）即可；矩阵与英文扫描都用 Session。

**M3 首页瘦身基线（DOM scrollHeight，越大越该瘦）**：

| 角色/页 | 1280 | 768 | 375 |
|---|---|---|---|
| guest /（官网首页） | 985 | 3929 | 5594 |
| student /my/home | **3744** | 3723 | 5889 |
| faculty /my/home | 1313 | 1371 | 1899 |
| parent /my/home | **3504** | 3481 | 5312 |
| backoffice /my/home | 1505 | 1563 | 2187 |

学生与家长首页在 1280 下都超过 3400px（≈ 4 屏），是 M3 的主要对象。

## 4. 待更新既有断言清单（结构改动会打红）

实测基线（2026-09-12 12:28，v3 结构改动之前）与打红原因：

| 位置 | 断言内容 | 当前基线 | 为何会红 | 建议 |
|---|---|---|---|---|
| `tests/smoke/smoke_student.py:70-73` | `/my/home` 的 `.o_portal_index_card` 数量 **≥10**（「功能卡网格≥10张」） | 实测 **47** 处命中 | v3 首页瘦身（M3）/ 改 Timeline 工作台后卡片数与类名都会变 | 改成「常用应用 + 分类区存在」的存在性断言，或改数据无关口径 |
| `tests/smoke/E_quiz_cross.py:317-321` | `id="searchBox"` 存在 + 用正则 `o_portal_index_card.*?href` 抓首卡 | 两者当前都命中 | 首页搜索框改名/换位、卡片 DOM 改版即红 | 改为查询语义容器（如 `[data-home-search]`）并放宽首卡抓取 |
| `tests/smoke/ux_rework_playwright.py:72-110` | 常用区编辑：`.ux-fav-category`、`a[data-app-href="library/media"]`、hover 后的 `[data-fav-act=pin/unpin/up]` | `data-app-href` 当前 38 个；`data-fav-act` 仅编辑态渲染 | 首页结构改动 → 选择器全失效 | 与 t6（首页改造负责人）约定稳定的 `data-*` 契约后再改断言 |
| `tests/smoke/G_messages_smoke.py:59` | `class="o_portal_index_card col-12 msg-conv"` 精确类名计数 | 实测 **2** 行 | 私信列表换类名/换卡片组件即红 | 改为 `.msg-conv` 子串 + `[data-conv-row]` 契约 |
| `tests/smoke/ux_rework_playwright.py:37-42`（**新增发现：与本任务无关、现在就会红**） | `page.goto("/web/login")` 后直接 `fill(input[name=login])` | 会落到 **/web/database/selector**，登录表单不存在 → 脚本必红 | 浏览器无 db cookie 时 Odoo 先给数据库选择页（本地库列表含 `edu19_relay_probe`） | 登录 URL 加 `?db=edu19`（`scripts/shoot_ux_v3.py` 已这么做），或按 t4 A3 关掉 `list_db` |
| `tests/smoke/smoke_student.py` 的 `do_login` | 同上（/web/login 无 db 参数） | 同上 | 同上 | 同上 |

> 纪律：本任务**不修改**既有冒烟脚本的断言（t3 nonGoals），只登记清单。
> 上述前 4 条由对应功能负责人在结构改动落地后同步更新；第 5、6 条属本地环境问题。

## 5. 环境问题与门禁预警（给 t4 brand-eng / t6 study-eng）

0. **t4 交付现状实测（2026-09-12 13:45 复采样，供 t10/t9 评审参考）**：
   匿名 `/login` → 200（渲染登录表单，应然）；**已登录 `/login` → 303 分流**：
   stu / faculty / parent → `/my/home`，backoffice → `/web`；
   带显式目标 `/login?redirect=/my/fees` → 303 → `/my/fees`（**有意为之**：不吞掉用户意图）。
   实现见 `edu_portal/controllers/main.py` 的 `EduHomeRedirect.edu_login`。
   （此前记过的「已登录仍渲染登录表单」WARN 属**旧构建状态**，13:25 起矩阵已无该 WARN。）
   `/apps`：学生 303→`/my/home`、教师 200（符合设计）；`/register` 200。

1. **匿名访问 `/` 会落到 Odoo 数据库选择页**（实证见截图 `tests/gap/shots/ux-v3/guest/1280/site_home.png`：
   Odoo 大 logo + `edu19` / `edu19_relay_probe` 两个库 + `Manage databases` 链接）。
   触发条件：浏览器无 db cookie 且库里存在第二个数据库 `edu19_relay_probe`（telegram relay 遗留）。
   带 `?db=edu19` 后一切正常（本次公开站截图即如此修复）。
   → 对应 t4 的 A3；建议同时清理 `edu19_relay_probe`，否则 `/web/login` 永远先给选择页。
2. **`check_odoo_trace` 的「0 命中」口径要先定义清楚**：仅 `/my/home` 一个页面，
   忽略大小写扫原始 HTML 就有 **12 处** `odoo`（`<meta name="generator" content="Odoo"/>`、
   `window.odoo`、`__odooAssetError`、`odoo.__session_info__`、`web.assets_*.min.js` 路径）。
   若直接对整页 HTML 扫 `odoo`，「0 命中」在不动前端 JS 的前提下不可达。
   建议口径：**只扫可见文本节点 + 可见属性**（复用 `check_english.py` 的剥离逻辑），
   技术性 JS 全局/资源路径另行登记为「不可见、允许保留」。
   （2026-09-12 复核：t4 的 `scripts/check_odoo_trace.py` 已按该口径实现——
   先剔 `<script>/<style>` 再扫可见文本，单独用 `GEN_RE` 处理 `meta generator`。）
   **2026-09-12 14:05 补一条实证（数据驱动的品牌泄漏）**：`/downloads` 的「上传人」列直接渲染
   `create_uid` 的显示名，而基座把超级用户改名为 `OpenEducat Bot`（`res_users.id=1`），
   于是**学生可见页面出现基座品牌** —— 这类泄漏**随数据出现/消失**（brand-eng 13:34 抓到、
   verifier 14:05 复测已 0），最容易在「我跑的时候是绿的」里漏掉。t8 已修
   （`controllers/downloads.py:205 _uploader_label()` → 技术账号统一显示「系统」）。
   → 门禁口径：`check_odoo_trace` 的路由清单必须含 v3 新页（`/downloads`、`/my/apps`、`/my/study` 等，见 t22），
   且要意识到 `odoo` 之外还有**基座品牌 `OpenEducat`/`OpenEducat Bot`** 与**技术模型名**两条同类泄漏。
   **⚠️ 两个门禁的属性盲区（2026-09-12 实测，务必记住）**：
   `check_odoo_trace`（v3.2 及以前）**只扫文本节点**（`TEXT_RE = >([^<>]{2,200})<`），**完全不扫属性**；
   而 `check_english` 虽扫 `title/placeholder/aria-label/alt`，但过滤器**含 CJK 即跳过**。
   两者盲区**恰好互补**：Odoo 的 `website/views/website_templates.xml:295` 有
   `title="Go to your Odoo Apps"` → 官方 zh_CN 渲染成「转到您的Odoo应用程序」（悬停可见），
   在 t26 给 `check_odoo_trace` 补上属性提取前，**两个门禁都报 0**（抽样口径的假绿）。
   → 判据：**"0 命中"必须写明口径**（文本节点 / 属性 / 两者）；两个工具的正交性不可互相顶替。

   **t22 已交付（v3.2，2026-09-12）**：`check_odoo_trace.py` 新增 `--selftest`（离线 10/10 PASS，含动态发现正则 4/4）、
   `--list-routes`（覆盖 23 → **50** 条；t26 再补后为 **51** 条：公开站 23 + 学生 10 + 教师 5 + 家长 3 + 教务 9 + 后台 1）、**动态发现**（跟进 `/my/study/<id>`、`/my/study/session/<id>/join`、
   `/my/courses/lesson/<id>`、`/my/calendar/ics/<token>`）。
   扩展覆盖后的中间命中：`教师 /my/study/35` 曾泄漏技术说明文案（`views/study.xml`，t6 领地）——
   **归 t6、已修**（verifier 复核：可见文本 `odoo`=0，全量扫描 0 命中 exit 0），**不计脚本 FAIL**。
    **口径/时间戳（2026-09-12 15:3x 补，避免被误读）**：上面这个"0 命中"是 **v3.2 文本口径、13:5x** 的结论；
    **t26 起口径扩到属性值后，当前是 23 处待修**（core tooltip，归 t29），t29 收口后才回到 0。
    **"0 命中"永远要连着口径与时间一起读。**
3. `<meta name="generator" content="Odoo"/>` 不可见但可被爬虫读取，是否清零由 t4 决策（覆写模板即可，代价低）。
4. 三个工具都是只读 GET；跑之前先确认 `curl -s -o /dev/null -w '%{http_code}' http://localhost:8069/web/login` 非 000。

### 5.1 `check_odoo_trace.py` 的认证与退出码（t79，2026-09-28 修）

**曾长期静默失效**：脚本 `BACKEND` 写死 `admin/admin`，而**本库 admin 口令是 `demo123`**
（`docs/deploy-malaysia.md:732`：「为实测编辑器，本地库 admin 口令被设为 demo123（仅本地，生产未动）」；
`tests/smoke/ux_v3_route_matrix.py:41-49` 已有同一份取证）。实测
`/web/session/authenticate(admin/admin)` → **HTTP 200 + `Access Denied`（uid=None）**，
于是脚本在**第 5 个（后台）面**上 `return 2` 退出，**退在汇总之前**：
数据不变量面、邮件面、边界计数、退出码判定一次都没跑过；而 `2` 的语义是
「环境不可用（没扫过）」，调用方读作「这次没看成」——
**前四个面已经扫出来的命中永远变不成 FAIL**（真实案例：`/alumni` 的
`/web/login?redirect=%2Falumni` 打印了 HIT，结论却永远是「环境问题」）。

修法（三条，缺一即复发）：
1. 口令只在一处声明（`CRED_DEFAULTS`），可被 `TRACE_<KEY>_LOGIN/PASSWORD` 覆盖；
   已知失效组合 `('admin','admin')` 进 `KNOWN_DEAD_CREDENTIALS`，selftest **断言不得回退**。
2. 登录失败 = **未验证面**（`AUTH_UNVERIFIED`）并**继续扫其余面**；未验证面按 t55 口径
   默认判失败（严格 1 / `--lenient` 3），**绝不产生 PASS**；只有「一个面都没登上」才走 ENV(2)。
3. 同族补洞：5xx 路由登记未验证面（旧实现拿 500 错误页当正文 ⇒ 假 PASS）；
   `PASS：…` 结论行曾写在 `return code` **之后**（死代码 ⇒ 退出码 0 时一行都不打印），
   现由纯函数 `verdict_line()` 产出、四个退出码各有自述并被 selftest 断言；
   另有 `prime()` 的 `except: pass`（选库失败 ⇒ 之后全 404 ⇒ 假绿）与
   邮件探针 `len=0` 被算作「渲染成功」（三语全失败照样上报 OK）两处静默，一并收口。

自证（可复现，正反双向）：
```bash
python3 scripts/check_odoo_trace.py                                            # 0 = OK（PASS 行含覆盖面自述）
TRACE_EXTRA_ROUTES='/web/reset_password' python3 scripts/check_odoo_trace.py   # 1 = FAIL（web-nav-link 命中）
TRACE_FORCE_HTTP_ENV_FAIL=1 python3 scripts/check_odoo_trace.py                # 2 = ENV
TRACE_FORCE_MAIL_UNAVAILABLE=1 python3 scripts/check_odoo_trace.py             # 1 = INCOMPLETE（默认 strict）
TRACE_FORCE_MAIL_UNAVAILABLE=1 python3 scripts/check_odoo_trace.py --lenient   # 3 = INCOMPLETE
TRACE_ADMIN_PASSWORD=wrong python3 scripts/check_odoo_trace.py                 # 1：后台面登记未验证面，其余面照扫
```

## 6. 有效基线（2026-09-12 13:14–13:27，稳定窗口取样）

**取样有效性**：
- 矩阵/英文：13:08–13:12 `SAMPLE_VALID`（Up 61s → 167s，无重启）。
- M3 截图：13:14–13:23 第 3 次尝试 `SAMPLE_VALID`（Up 64s → 141s，无重启），69 张截图、`SHOTS_EXIT=0`。
- 取样前均通过 §0 三步探活 + 目标页非 5xx 检查。

```bash
python3 scripts/check_english.py --selftest                 # exit 0，23 项断言全 PASS
python3 tests/smoke/ux_v3_route_matrix.py                   # exit 0，PASS 497 / WARN 3 / PENDING 0 / FAIL 0 / ENV 0
python3 tests/smoke/ux_v3_route_matrix.py --role stu        # exit 0，PASS 98 / WARN 0 / PENDING 2 / FAIL 0 / ENV 0
python3 scripts/check_english.py                            # exit 2，must-fix 见下表（Telegram/Administrator 已按 2026-09-12 决议归 whitelist/data）
python3 scripts/shoot_ux_v3.py                              # exit 0，69 张截图 + 下方 M3 表
python3 tests/smoke/zero_loss_reachability.py               # exit 2，L1 39/39，L2 待 /my/apps 交付
```

> **全量矩阵（5 角色 × 100 路由）13:25–13:27 稳定窗口复跑（SAMPLE_VALID，Up 62s→83s，探活 302）**：
> `MATRIX_EXIT=0` —— **PASS 497 / WARN 3 / PENDING 0 / FAIL 0 / ENV 0**；
> 唯一 WARN 是 `/my/checkin/board` 对 fac / bo / admin 的 404（该路由设计上只给学生/家长）。

**check_english（must-fix = 0 ✅ 首次全绿；2026-09-12 13:30–13:31 稳定窗口，SAMPLE_VALID，Up 62s→80s）**

| 角色 | 路由数 | must-fix | whitelist | data | theme |
|---|---|---|---|---|---|
| guest | 21 | **0** | 60 | 26 | 38 |
| student | 67 | **0** | 224 | 131 | 122 |
| faculty | 86 | **0** | 277 | 140 | 150 |
| parent | 67 | **0** | 215 | 73 | 116 |
| backoffice | 86 | **0** | 270 | 143 | 146 |
| **合计** | — | **0** | 1046 | 513 | 572 |

`python3 scripts/check_english.py` → **exit 0**（此前 exit 2；唯一失败条件 = must-fix 命中数 > 0）。
登记项 2131 条不计失败：whitelist（品牌名/口号、Zoom、Telegram、English/EN 语言自称）、
data（CRS-* 课程代码、pdf、邮箱、Administrator 账号显示名）、theme（编辑器 navbar 区块的 Main/Mobile 等）。

**清零路径与成果归属（队长 2026-09-12 更正后的口径，交付报告不得串）**

| 批次 | 清掉的 must-fix | 归属 |
|---|---|---|
| t17（brand-eng，inScope 五文件） | 8 类：breadcrumb×20、Home×4、Search library×4、Teacher/Parent/Backoffice/Administrator login 各 1、Add Your Skill×1、Apply×5、Course 本文件侧×2 | brand-eng |
| t6（study-eng） | `/my/apps` 与门户外壳的 Notifications / Open profile / Search anything... / Search / Contact 共 28 处（`batch2.xml`、`edu_portal_templates.xml`） | study-eng |
| /edu/audit 中文实体名 | OpenEducat Bot + `edu.approval.delegate`/`op.subject.registration`/`edu.leave`/`edu.grievance` 共 8 处 | flow-eng（t7） |
| `/courses-offered` 标题 | `<title>Course</title>` → **「开设课程」**（渲染实测已确认） | i18n-eng（edu_public） |
| 分类口径（非内容修改） | EN→whitelist、Telegram→whitelist、Administrator→data、`<template>` 区块免扫 | verifier（t16） |

**已闭环的历史 must-fix（同日修复，复测确认消失）**

| 曾命中 | 次数 | 处理 |
|---|---|---|
| Notifications / Open profile / Search anything... / Search / Contact | 28 | t6 汉化 `/my/apps` 与门户外壳属性（渲染实测 0 残留） |
| OpenEducat Bot + 4 个技术模型名 | 8 | flow-eng 加中文实体名映射 |
| Course | 5 | `/courses-offered` 标题改「开设课程」（`<title>Course</title>` 计数 0） |
| Telegram / Administrator | 2 / 4 | 产品名进 whitelist / 账号显示名归 data |

**M3 首页高度（DOM scrollHeight，2026-09-12 13:23 有效基线）**

| 角色/页 | 1280 | 768 | 375 |
|---|---|---|---|
| guest /（官网首页） | 3666 | 3929 | 5594 |
| student /my/home | 1366 | 1434 | 1449 |
| faculty /my/home | 1313 | 1371 | 1948 |
| parent /my/home | 1082 | 1198 | 1013 |
| backoffice /my/home | 1505 | 1563 | 2236 |

> ⚠️ **作废数据**：曾经出现过的 student/home `900/1024/812`、parent/home `900/1024/921` 是
> **错误页高度**（取样窗口内的 HTTP 500 错误页正好等于视口高），**不是首页真实高度，禁止引用**。
> ⚠️ 说明：student/home 从 12:28 的 **3744** 降到 1366，是 t6 首页重构（35 卡移入 /my/apps）的结果 ——
> 即「改前 3744 → 改后 1366」，已满足 t6 的「桌面 ≤1800 / 375 ≤2600」两个目标。

**登记项说明（不计失败，但要知道里面有什么）**：
`theme` 桶包含 website 编辑器 navbar 区块的**全部内容**：既有 `aria-label="Main"/"Mobile"`（不可见属性，
本不该修），也有**可见的导航菜单文本**（`Course`/`Program`/`Alumni Jobs` 等各 504 次）。
若要汉化菜单项，把 `classify()` 的 theme 分支收窄成「仅属性命中」即可（一行改动），
届时应把它们从 theme 移到 must-fix —— 这是留给 t4/i18n 的显式决策，不要用白名单掩盖。

## 7. 运行窗口提示（实测踩坑，按时间排序）

1. **升级窗口里的「假红」**：2026-09-12 12:30–12:34 站点对所有路由 500，原因是
   `ModuleNotFoundError: No module named 'odoo.addons.edu_zh'`（有人正在装 `edu_zh`，registry 未加载成功）。
   同一窗口跑门禁会得到满屏 500。→ 矩阵脚本已内置探活（`GET /web/login` 5xx 直接 exit 2）；
   人肉排查先看 `docker compose logs web --tail 40`。
2. **代码回归（不是环境）**：2026-09-12 12:32:51 起全站不可用，根因是**循环导入**：
   `edu_portal/controllers/__init__.py` → `main.py:11 from .register import EduRegister`
   → `register.py:118 from . import contacts` → `contacts.py:23 from .main import current_student`
   → main 尚未执行完 → `ImportError: cannot import name 'current_student' from partially initialized module`。
   后果：`Couldn't load module edu_portal` → registry 加载失败 → 登录 POST 返回 200 但带 error、门户全红。
   三个门禁都如实报了出来（矩阵 exit 2 + 服务端原始错误、check_english 各角色「登录失败」）。
   最小修法（供 t4 参考）：把 `from .register import EduRegister` 移到 `main.py` **文件末尾**
   （与 `register.py` 末尾导入 contacts 的既有约定一致），或在 `controllers/__init__.py` 保证 main 先于 register 导入。
3. **多库 + list_db=False 的「nodb 假崩」**（队长 2026-09-12 定位，已实测确认）：
   `config/odoo.conf` 12:27:56 改为 `list_db = False`，本地 Postgres 有 `edu19` 与 `edu19_relay_probe` 两个库，
   容器启动又没带 `-d edu19` → **不带库名的请求全部进 nodb 路由表**（日志反复 `request._serve_nodb()`），
   表现为大部分路由 404、`/web/login?db=edu19` 自跳 302。带库名（`?db=edu19` 或会话里已选库）一切正常。
   → 修法（t4/brand-eng）：`config/odoo.conf` 加 `db_name = edu19`（保留 `list_db=False`），或兜底改回 True。
   本仓三个门禁**全部带库名运行**（JSON-RPC 带 `db`、Playwright 用 `?db=edu19`），因此不受该故障影响；
   受影响的只有「裸 curl / 不带 db 的浏览器访问」。
4. **`op_subject.credit_points` 列缺失 → `/my/calendar` 全角色 500（13:10 实测；同日闭合）**

   症状：`/my/calendar` 全角色 500、`/my/home` 学生 500 / 家长 404；服务端
   `ERROR: column op_subject.credit_points does not exist`，栈
   `edu_portal/controllers/calendar.py:348 my_calendar → :479 _calendar_month`；
   字段定义 `edu_portal/models/registration.py:251`。

   **根因（2026-09-12 由 study-eng 更正，verifier 原判"漏 `-u`"不准确）**：不是没人升级，而是
   **`-u edu_portal` 被同期别人的视图错误连续打断** ——
   ① 13:11 lxml `XMLSyntaxError: StartTag: invalid element name`（`roles.xml:631` 的 `<script>` 里 JS 裸 `<`）；
   ② 13:13 `odoo.tools.convert.ParseError`：上级视图内找不到 `<xpath expr="//table/tbody/tr/td[1]">`（`edu_registrar_subject_approvals_bulk`）。
   两次都 EXIT=255，**`_auto_init` 根本没执行**，列建不出来；flow-eng 修好后第三次 `-u` 成功（SAFE_EXIT=0），列即那时建出。
   → 教训：**升级失败会被"上一个人的错误文件"阻塞**，而且症状表现为"列/视图不存在"（看起来像漏升级）。

   **可独立复核的部分**：`information_schema` 中 `op_subject.credit_points` 计数 = 1；
   四角色 × `/my/home`、`/my/calendar`、`/downloads`、`/my/study`、`/my/apps` 全 200。
   **无法独立复核的部分**：两次失败升级的原始输出（`/tmp/edu19_upgrade.log` 被后续成功升级覆盖，
   容器日志不含 exec 子进程输出）——该段以 study-eng 的一次性报告为准。

5. **`-u edu_apply` 曾撞 `UNIQUE(name)`（2026-09-12 报出，同日 t18 已修复）**

   **症状与根因**：孤儿行 `edu.apply.field(id=32, name='name')` 丢了 `edu_apply.fld_name` 映射 →
   `-u edu_apply` 按 CREATE 处理 → 撞唯一约束 `edu_apply_field_name_uniq = UNIQUE(name)` →
   `ParseError`；**升级与部署双阻断**（`scripts/deploy_myedu.sh` 也跑 `-u`）。

   **修复（t18）**：`scripts/fix_edu_apply_xmlid.py` —— 幂等，只建映射、绝不删行、不动 label/required/locked/active；
   建映射前先校验既有行与 XML 声明一致，不一致则 `ABORT` 交人工。

   **verifier 独立复核（2026-09-12 13:55）**：
   - `ir_model_data`：`edu_apply | fld_name | edu.apply.field | res_id=32 | noupdate=t` ✓
   - 孤儿普查 SQL（"同名行无映射"）→ **0 行** ✓
   - 独立跑 `FIX_DRY_RUN=1`（`odoo shell`，只读）→ `SKIP edu_apply.fld_name：映射已存在 → res_id=32`，
     输出「无同型孤儿」，`env.cr.commit()` 未触发（未提交）✓
   - **verifier 独立重跑 `bash scripts/safe_upgrade.sh -u edu_apply` → `SAFE_EXIT=0`**（2026-09-12 13:58，脚本自带的就绪探活 `/web/login?db=edu19 → 302` 通过、报「无失败特征」）；
     `/tmp/edu19_upgrade.log` 里 `ParseError` / `Traceback` / `CRITICAL` / `already exists` / `duplicate key` **均为 0**；
     升级前后数据一致：`edu_apply_field` 32 行、label 聚合 md5 `f194dc30cc24a13318c6745a4bc56a5b` 不变；
     `ir_model_data` 映射仍在（`res_id=32, noupdate=t`）；`/apply` → 200 且 `<input ... name="name" required="required">` 仍在。
     升级后等稳定窗口复跑 `ux_v3_route_matrix.py --role stu` → `STU_EXIT=0`（PASS 100 / WARN 0 / PENDING 0 / FAIL 0 / ENV 0）。

   **生产预部署步骤（记入部署清单）**：
   1) 生产容器干跑 `-e FIX_DRY_RUN=1` → `SKIP`=可直接部署 / `DRY`=存在同型孤儿 / `ABORT`=停止并人工核对；
   2) 若为 `DRY`：先跑脚本补映射（看到 `FIXED` 或 `SKIP` 且无 `ABORT`）；
   3) 再执行 `deploy_myedu.sh`；
   4) 部署后抽查 `/apply` 200 且姓名必填生效。
   **生产是否受影响：未确认**（未对生产库做任何探测）。

6. **结论**：有效基线 = 2026-09-12 13:03–13:12（见 §6，已过三步探活 + 前后 StartedAt 校验）。
   跑任何门禁前先做 §0 的三步探活；模块改动后一律 `bash scripts/safe_upgrade.sh <模块>` 再重跑。
## 8. 零功能丢失门禁（zero_loss_reachability.py）

依据 `docs/plans/study-hub-v3-design.md` §6 / §10.3；把「旧首页 35 张卡零丢失」从设计声明变成机器可验证。

```bash
python3 tests/smoke/zero_loss_reachability.py            # L1(admin+student) + L2 + L0
python3 tests/smoke/zero_loss_reachability.py --role admin
python3 tests/smoke/zero_loss_reachability.py --json /tmp/zl.json
```

三层断言：

- **L1 可达性**：35 张旧卡 + 9 张动态注入卡的 href 逐条 GET（跟随跳转，最多 4 跳），
  期望 200 或 3xx→最终 <400。**6 张默认隐藏卡同样必须可达**（`batch2.py:292 _DEFAULT_HIDDEN_CARDS`）：
  其中 `help` / `student/timetable` / `my/academic-calendar` 实测 200；
  `my/rfq` / `my/purchase` / `student/newregistration/info` **改动前就 404**（batch2.py:293-294 自认「路由缺失」），
  记为 `BASELINE-404`≠回归，但不隐藏。
- **L2 IA 覆盖**：抓 `/my/apps` 的 HTML，断言 35 条 href 全部出现（`href="/<href>"`，默认隐藏卡豁免）。
  L1 只证明 URL 打得开；**只有 L2 能抓到「卡被删掉」**。
- **L0 共享类契约**：`.o_portal_index_card` 被 7 个模板共用（batch2 / contacts / edu_portal_templates /
  help_center / messages / roles），首页重构**不得改名或删除**；脚本核对
  `/my/messages`（4 处）、`/my/contacts`（4 处）、`/my/child`（1 处）仍渲染该类，
  `/my/home` 的卡片数只记录不判失败（重构本来就会下调）。

**基线（2026-09-12，`/my/apps` 未交付前）**：L1 39/39 可达（其中 3 条 BASELINE-404），L2 无法判定 → `exit 2`。
交付 `/my/apps` 后应转为 `exit 0`（L2 缺失 0）。
## 9. 数据驱动的品牌泄漏门禁（t9 固定检查项）

**为什么单列**（队长 2026-09-12 定）：页面渲染 `create_uid` / `write_uid` / `user_id` 的**显示名**时，
若该数据由**技术账号**创建（基座把超级用户改名为 `OpenEducat Bot`，`res_users.id=1`），
基座品牌就会出现在学生可见页面上。这类泄漏**随数据出现/消失**：今天数据里没有机器人建的行 → 全绿；
明天有人用机器人账号建一条 → 立刻冒出来。**路由全 200 与静态文本扫描都拦不住它。**

```bash
python3 tests/smoke/data_driven_brand_leak.py                 # 默认：只读复用库内既有技术账号数据
python3 tests/smoke/data_driven_brand_leak.py --create-sample # 库内无技术账号数据时补一条【冒烟】样本（用后自动删）
python3 tests/smoke/data_driven_brand_leak.py --json /tmp/leak.json
```

方法（可复现三步，脚本已实现）：

1. **取数/构造样本**：先数 `edu_download_file` / `edu_audit_log` 里 `create_uid=1` 的行；
   有就不造样本（只读），没有才经 `odoo shell` 以 `with_user(1)` 造一条 `【冒烟】…` 样本；
2. **断言**：逐角色抓 `/downloads`、`/downloads/mine`、`/downloads?mode=manage`、`/edu/audit`，
   **可见文本**里 `OpenEducat` 家族字样必须为 0；同时做**正向断言** —— 有技术账号数据时页面必须出现「系统」
   （防止「恰好没数据所以恰好没有」的假绿）；
3. **清场**：造过样本就删除，**leftover 以 psql 直查为准**（不信 shell 的 print）并输出 `leftover=0`。

## 10. 可用性门禁（`scripts/check_ui_usability.py`，2026-09-28 立）

**为什么单列**：七轴体检（`docs/audit/ui-gap-ledger.md`）的结论是 —— **结构门禁抓不到「按钮跑出屏幕」这类缺陷**。
两条独立证据：① 已覆盖的**对照组**问题率**反而更高**（35% vs 死角组 27%）= 覆盖度 ≠ 质量；
② 对照组自己也带着一条 P1：`/leave/approvals` 在 375 视口横向溢出，「批准」按钮 rect 超出视口
⇒ **手机上审批请假要横滑才能按**。三个结构门禁（route_matrix / accessibility / english）判的是
「不 5xx / 不大面积 404」「英文词表」「axe 无障碍」，**判据里没有一条是「元素在不在视口内」**。
⇒ 只补覆盖，这类问题下次照样漏。

### 怎么跑（**先读这条，否则会以为门禁坏了**）
本仓默认 `python3` 是 **3.9，没有 playwright**。带 playwright 的解释器：

```bash
/opt/homebrew/bin/python3          # 3.14.6  ← 优先
/Users/qwe/miniconda3/bin/python3  # 3.13.13（备选）
```

```bash
/opt/homebrew/bin/python3 scripts/check_ui_usability.py --selftest   # 先证量具
/opt/homebrew/bin/python3 scripts/check_ui_usability.py --baseline   # 冻结存量（ratchet 起点）
/opt/homebrew/bin/python3 scripts/check_ui_usability.py --check      # 只报**新增/恶化**（部署前的门禁口径）
/opt/homebrew/bin/python3 scripts/check_ui_usability.py --report     # 打印全部当前命中
```

### 四条轴（判据必须客观可复算；判断型的轴留给人工体检）
| 轴 | 判据 |
|---|---|
| **A 横向溢出** | 375 视口 `documentElement.scrollWidth − clientWidth > 8px` ⇒ 报红 + 溢出像素数 |
| **B 主操作横向越界** | 按钮 rect **且与视口横向相交**时：`right > 375` 或 `left < 0` ⇒ 报红；纵向只认 `bottom < 0` |
| **C 中文措辞错** | `tests/ui/wording.json` 对照表**逐字相等**命中（且元素非交互控件）⇒ 报红 |
| **D 空态无出口** | 无列表行且无卡片（判为空态）且页内**没有任何指向他页的 `a[href]`** ⇒ 报红 |

### 两条**已经踩过的假红**，已固化成回归守卫（谁再改回去就会被自证拦住）
1. **纵向折叠线以下 ≠ 缺陷**：旧 B 判据用「下边界 > 视口高 ×1.5」，实测在 `/leave/approvals` 上
   一次误报 **9 个按钮**（理由都是「下溢 2645~2680px」）—— 那只是页面长。**B 现已只判横向。**
2. **完全在视口外 ≠ 缺陷**：a11y 的 skip-link（「跳至内容」）实测 rect `(left -1, right 0)`、宽 1px，
   被旧判据的 `left < 0` 直接误抓；`left:-9999` 的藏件同理。**现要求「与视口横向相交」才判。**

### 自证纪律（**这条是本次的教训，比代码更重要**）
自证的正样本**必须自给自足** —— 用**合成夹具**喂纯函数 `judge()`，**不许依赖「某个真实 bug 还在」**。
反例就发生在建这条门禁的当天：正样本原本用真实页 `/leave/approvals` 的横向溢出，
**D 组把它修好（126px → 0px）之后，「正样本应报红」必然失败** ⇒ 门禁与实物脱节、自证永远红。
真实页只用于两件事：**渲染得出来**（环境检查）、**干净页确实干净**（负样本）。

### 与结构门禁的分工（两层，别混）
| 层 | 门禁 | 频率 |
|---|---|---|
| 地板 | route_matrix / accessibility / english / `check_ui_surface.py` / `check_docs_index.py` | **每次提交**（`code-map §10` 的离线自证链 + commit 前） |
| 体检 | **本门禁** + 人工七轴体检 | **周期性 + 部署前**（需要活站点与浏览器，**不进** §10 的离线链） |

### 节奏（建议）
- **部署前必跑** `--check`（只报新增/恶化，基线已冻结就不会被存量噪声挡住）
- 每次动门户模板/CSS 后跑**受影响页**的 `--report`
- 人工七轴体检按其自身节奏跑（它抓的是本门禁判不了的：空态质量分级、措辞是否通顺、任务能否走完）


**本机实测（2026-09-12 14:12）**：`LEAK_EXIT=0` —— 5 个页面品牌字样 0 处，`/edu/audit` 出现「系统」×2；
样本生命周期自测：`created id=44 → deleted=1 leftover=0`（psql 复核 0 行）。
老工具 `scripts/check_odoo_trace.py` 的路由清单不含 `/downloads` 等 v3 新页（t22 补），
所以这条以前只有 `check_english` 拦得住文本型。

> **口径提醒（队长 2026-09-12）**：「门禁全绿」与「特定数据形态下的正确性」要分开陈述 ——
> 这是 ENV/真红分离的延伸。

### 9.1 根因仍在：显示名数据（2026-09-12 brand-eng 探测 + verifier 复核）

`_uploader_label()` / `_audit_user_label()` 是**逐页防护**（防御纵深），但根因在数据里：
```sql
select u.id, u.login, p.name from res_users u join res_partner p on p.id = u.partner_id
 where u.id = 1;          -- 实测： 1 | __system__ | OpenEducat Bot   （base.partner_root = res.partner(2)）
```
→ **任何新页面/新列**（chatter、审计列、导出、未来的作者列）忘了套过滤就会再漏一次，
且漏不漏取决于数据当时落在哪一页 —— 这就是「页面扫描天生是抽样」的含义。

**处置（建议，需派任务）**：
- **数据侧治根**：在 `edu_brand/data_brand/brand_debrand_data.xml` 用
  `<function model="res.partner" name="write" eval="[[ref('base.partner_root')], {'name': '系统'}]"/>`
  每次 `-u` 重放（可重复、非手工改库）。verifier 已核查**无依赖会断**：
  `_TECH_LOGINS` 与 `cleanup_demo_data.py` 都按 **login** 匹配；`check_odoo_trace` 里的两处是 selftest 硬编码样本；
  逐页过滤的 `user.id == 1` 分支仍在。附带收益：邮件/通知作者名不再出现基座品牌。
- **门禁侧兜底**：给 `check_odoo_trace.py` 加"数据不变量判定"（根因而非抽样）。
  **范围必须限定技术账号**（`uid=1` / login 命中 `__system__|__oe__|OdooBot|public`），
  **不要**扫全部 `res.partner.name`，否则将来学员/机构名含 odoo/bot 会误报。

---

## 11. 无障碍门禁的后台页覆盖（2026-09-28 补；原先本门禁是「门户专用」）

> 起因：`.oe_topbar_name`（后台导航栏里的公司名「永约学坊」）字色 = 原厂 `rgba(255,255,255,.9)`，
> 压在**我们的** `--brand-action #0C6DD7` 上只有 **4.372 ✗**（AA 需 4.5）。同根因的还有整片导航栏条目
> （`.o_menu_brand` / `.o_nav_entry` / 下拉条目 / systray 各项）—— 它们全是原厂按**原厂紫** `#71639E` 调的档
> （.9 白压紫 = 4.635 ✓），我们换底后就掉档。

### 11.1 为什么以前没人发现（两条，都是实测/源码级，不是猜测）

1. **门禁不扫后台页**：`scripts/check_accessibility.py` 的扫描面来自 `tests/ui/surface.json`（gates 含
   accessibility），而那张表由 `scripts/ui_surface_report.py --generate` 从
   `custom_addons/**/*.py :: @http.route` 生成 —— **后台 Web 客户端是 Odoo 核心路由，不在 custom_addons 里**，
   所以生成器看不见它，表里也就永远没有后台页（原先 29 条路径**零后台页**；`/` 那处补偿条目是同一类问题的先例）。
2. **即使扫了后台页，axe 也看不见这个元素**（更隐蔽）：axe-core 4.10.2 的 color-contrast 匹配函数
   开头是 `isDisabled(virtualNode) || isInert(virtualNode) → return false`，而 `isDisabled` **向上继承**
   （`lib/commons/forms/is-disabled.js`：非表单元素走 `virtualNode.parent` 递归）。本库只有一个公司
   ⇒ Odoo 把公司切换器按钮渲染成 `<button disabled>` ⇒ 里面的公司名 span 在 violations / incomplete /
   passes **三处皆无**。WCAG 1.4.3 对 disabled 控件本就豁免，所以这不是 axe 的 bug，是**覆盖盲区**。
   （实测复现：把同款 span 克隆进 `.o_menu_systray` 立刻被判 4.36 违规；留在原按钮里一次都不出现。）

### 11.2 现在的口径（两层，别混）

| 层 | 内容 | 是否进基线 |
|---|---|---|
| **判据** | 外壳 `.o_navbar` 的 color-contrast ＋ 任何**未登记** axe 规则 ＋ 本地对比度检查 `shell-contrast` | **零容忍**（基线仍是 0） |
| **核心清单** | Odoo 核心渲染的页面主体与核心 ARIA 结构（role-img-alt / label / meta-viewport / html-has-lang / role=menu 等） | **不进基线**，但逐条打印 + 落 JSON；**出现未登记规则即判红** |

- 本地对比度检查（`shell-contrast`）**必须存在**：它按「文字色（含 α 合成）vs 有效底色」逐条实算，
  **不跳过 disabled** —— 这正是 axe 扫不到的那一格（公司名就在 disabled 按钮里）。
- 后台是 Owl **异步挂载**：`domcontentloaded` 时导航栏常常还没渲染（实测 rect=0）⇒ 门禁先等外壳出现并稳定；
  **外壳量不到 ⇒ 按未扫到处理（exit 3 INCOMPLETE）**，绝不当作「零违规通过」。

### 11.3 怎么复跑「注入违例必须变红」（反向证明，3 分钟）

```bash
# ① 把修复撤掉（= 恢复原厂 90% 白，即修复前状态）：
#    custom_addons/edu_brand/static/src/css/backend_b11.css 里注释掉
#    --NavBar-entry-color: var(--white); 与 --NavBar-brand-color: var(--white); 两行
bash scripts/safe_upgrade.sh edu_brand                      # 静态资源必须走 -u 才会重建 bundle
python3 scripts/check_accessibility.py --only /odoo/contacts,/odoo/students
# 实测（2026-09-28）：exit 2，违规 10 条 = shell-contrast 6（含
#   span.oe_topbar_name … 4.372 < 4.5（disabled 控件内））+ color-contrast 4（启用的菜单条目）
# ② 还原修复后复跑：exit 0（判据 0 条；核心清单照旧打印）
```

### 11.4 已知残留（**已上报队长，未修**：属 Odoo 核心渲染，不在本仓可改范围）

实测（2026-09-28，`--only /odoo/contacts,/odoo/students`）：核心清单 8 种规则 / 120 条节点 ——
`role-img-alt` x88、`label` x19、`aria-allowed-attr` x4、`aria-required-children` x3（外壳 `.o_menu_sections`/`.o_menu_systray`）、
`html-has-lang` x2、`meta-viewport` x2（后端 layout 关掉了缩放）、`button-name` x1、`aria-required-parent` x1（外壳 `.o_menu_brand`）。
其中 `aria-required-children` / `aria-required-parent` 在**外壳里**（结构是 Odoo 核心 navbar 模板定的：`role="menu"` 装非 menuitem 子节点）；
要收口得改核心模板/JS，属另立任务。**本轮没有把它们塞进任何白名单**：它们逐条打印，出现新规则立即判红。

### 11.5 修复本身（`custom_addons/edu_brand/static/src/css/backend_b11.css`）

```css
.o_web_client .o_main_navbar{
  --NavBar-entry-color: var(--white);   /* 90% 白 4.372 ✗ → 不透明白 5.019 ✓ */
  --NavBar-brand-color: var(--white);
}
```
- **为什么覆盖自定义属性而不是改 `$o-navbar-entry-color`**：那个 SCSS 变量编在 `web._assets_primary_variables`
  （**前后台共用**），改它会连网站前台的 navbar 一起变（前台可能是浅底，白字会从合格变不合格）；
  挂在 `.o_web_client` 上只动后台 Web 客户端。
- **逐条实算（不是抽一个）**：`/odoo/session`（16 条目）+ `/odoo/students`（4 条目）+ `/odoo/contacts`（1 条目）
  + 公司名 + 用户徽标，全部 4.372 → 5.019（**IMPROVED 28 处 / WORSE 0 处**，门户页无 `.o_main_navbar` 不受影响）；
  三态实测：常驻 5.019 ｜ hover 5.735 ｜ active 5.735（黑叠层压深底色）。
- 取色/合成/比值算法与门禁同源（`contrast_ratio` / `composite` / `needs_large_ratio`），
  `--selftest` 里钉着 5.019 / 4.372 两个档，改坏量具会被自证拦住。
---

## 12. 后台无障碍覆盖 2 页 → 7 页（2026-09-29；含 role=menu 机制查证、窄视口实测、违规归属分流）

> 采集时刻：**2026-09-29 14:20–15:05（本地 edu19，axe 4.10.2，Chrome headless 1280x900 除注明外）**。
> 复跑命令逐条写在各小节里 —— 下面的数字都是**那一轮**的读数，不要当常量引用。

### 12.1 覆盖矩阵：为什么是这 5 页（视图形态各一类，逐条给了理由）

| 视图形态 | 路径 | 为什么选它 | 实测形态（--expect-form 断言） |
|---|---|---|---|
| 列表 | `/odoo/contacts` | 核心 `res.partner`，80 行 / 81 选择框，最稳 | `list` |
| 列表 | `/odoo/batches` | **自研** `op.batch`（17 行 / 35 选择框）+ 应用内区段导航 | `list` |
| 列表 | `/odoo/grade-configuration` | **另一个应用**（时间表/考试）的配置分区，区段形态最复杂（6 扁平项 + 8 下拉按钮） | `list` |
| 看板 | `/odoo/students` | 自研应用根 `op.student`（14 卡）+ 区段导航 | `kanban` |
| 看板 | `/odoo/apps` | 核心 `ir.module.module`（73 卡带图标）**无区段**，与上一行成对照 | `kanban` |
| 表单 | `/odoo/contacts/1` | 核心记录表单（无区段） | `form` |
| 表单 | `/odoo/students/5` | 自研记录表单（有区段） | `form` |

- **「设置」形态如实登记为覆盖缺口**：`/odoo/settings` 在 backoffice 下是 Access Error、在 admin 下是
  HTTP 200 + 整页 RPC 500（`Field res.config.settings.edu_apply_deadline must have type …`，
  抛点 `base/models/res_config.py` 的 `_get_classified_fields`）⇒ **任何人**都打不开。
  不拿别的页冒名顶替，也不登记它（登记只会得到「200 + 错误弹窗」的假覆盖）。
- **形态断言**（`BACKEND_EXPECT_VIEW` + `backend_view_ok`）：带记录 id 的样本一旦记录消失，URL **仍返 200**
  只是静默回落成默认视图（实测 `/odoo/students/1` ⇒ kanban）⇒ 判 INCOMPLETE（exit 3），不判绿。
- 复跑：`python3 scripts/check_accessibility.py --only /odoo/contacts,/odoo/students,/odoo/batches,/odoo/apps,/odoo/contacts/1,/odoo/students/5,/odoo/grade-configuration`

### 12.2 扩覆盖扫出来的 16 条（全部核心渲染）+ 修复（backend_debrand.xml 属性级继承）

| 规则 | impact | 条数 | 元素 / 源码依据 | 处置 |
|---|---|---|---|---|
| `image-alt` | critical | 5 | `mail/static/src/core/common/message.xml` 的 `img.o-mail-Message-avatar` 无 alt | 头像退化为装饰：`aria-hidden="true"` |
| `aria-prohibited-attr` | serious | 5 | 同一 patch（`mail/…/web/message_patch.xml`）给 `div.o-mail-Message-avatarContainer` 加了 `t-att-aria-label` 却没给 role | 容器**本来就可点**（同一 patch 挂了 `t-on-click`）⇒ 补 `role="button"` |
| `list` | serious | 4 | 同一 patch 的 `<li class="o-mail-Message-tracking" role="group">` 让 `<ul>` 直接子元素不是 listitem | 删掉那个多余 role（`<li>` 本来就是 listitem） |
| `aria-roles` | critical | 1 | `web/static/src/search/search_bar/search_bar.xml` 的 `role="image"` —— **不是合法 ARIA role** | 删该属性（图标本是装饰） |
| `aria-command-name` | serious | 1 | 同模板 `.o_searchview_facet_label` 是 `role=button`（`facet.domain` 时）却无可访问名 | `t-att-aria-label="facet.domain ? (facet.title || '编辑筛选条件') : undefined"` |

- **改后逐条读数**（不是汇总）：`image-alt 5→0`、`aria-prohibited-attr 5→0`、`list 4→0`、
  `aria-roles 1→0`、`aria-command-name 1→0`；7 页判据 **16 → 0**，且
  **7/7 页 console 报错 0 条 / 未捕获异常 0 条**（Owl 模板继承命不中 xpath 会抛错并让整个资产包挂掉 —— 上一轮踩过，
  所以这条现在是量具的一部分：`tests/smoke/a11y_backend_pages_probe.py` 与 `--expect-form` 一起跑）。
- ⚠ **第一次 `t-att-aria-label="facet.title"` 实测无效**：带图标的筛选胶囊上 `facet.title` 是 undefined
  ⇒ 渲染出「没有 aria-label」⇒ 违规照旧。**只有实测才会发现**这种「改了但没生效」。
- ⚠ **「bundle 哈希变了」不是可靠判据（本轮实测反例）**：同一次改动前后 `/web/assets/<hash>/` 三个哈希
  **完全没变**，而 bundle 内容**确实变了**（在 `registerTemplate("web.SearchBar.Facets", …)` 里能 grep 到新 xpath）。
  判「改动到底有没有上线」的**可靠做法**是 grep 产物内容本身：
  `curl -s <bundle 的 js URL> | grep "t-att-aria-label"`。
  ⚠ 另：本文件的改动**需要** `bash scripts/safe_upgrade.sh edu_brand`（Owl 模板编译进资产包）。

### 12.3 role=menu 那几类：机制 + 能不能修 + 代价（**结论：维持只读数；「补 menuitem」已被实测否掉**）

**谁给的 role**（core 源码，非猜测）：`web/static/src/webclient/navbar/navbar.xml` 两处 ——
`.o_menu_systray` 与 `.o_menu_sections` 都是 `role="menu"`；
子节点里 `role="menuitem"` 来自 **`web.DropdownItem` 写死的 role**（`core/dropdown/dropdown_item.xml`），
而**没有 role 的那些子节点**是核心自己渲染的 `<button class="o-dropdown dropdown-toggle">`
（有子菜单的区段按钮 / More 按钮）与 systray 各组件的根 `div`。

**实测**（`tests/smoke/a11y_menu_role_probe.py`，14 组内存对照实验，逐组整页跑 axe）：

| 实验 | required-children | required-parent | 新引入的规则 |
|---|---|---|---|
| E0 基线（/odoo/students） | 2 | 1 | — |
| E1 systray 去 role=menu | 1 | 1 | 无 |
| E2 sections 去 role=menu | 1 | **3** | 无 |
| E3 两个都去 | 0 | **3** | 无 |
| E4 两个换 role=toolbar | 0 | 3 | 无 |
| E5 **给子项补 role=menuitem** | 0 | 1 | **aria-command-name x9** |
| E6 只去 `.o_menu_brand` 的 menuitem | 2 | **0** | 无 |
| E9 = E1+E6 | **1** | **0** | 无 |
| E12 = E1+E6+E8 | **0** | **0** | 无 |

- **去掉 role=menu 会引出别的规则**：会 —— sections 一去掉，它的 `menuitem` 子项立刻变成
  `aria-required-parent`（1→3）。`role=toolbar` 不是 `menuitem` 的合法父，同样不好使。
- **补 menuitem 是负收益**：E5 引入 `aria-command-name x9`（systray 里那些无名 div 被声明成 menuitem）。
  ⇒ 队长 2026-09-29 裁定**否掉这条路**。
- **能不能修**：三条属性级改（E12）理论上能把这两类清零（且不引入新规则），但它们都要 xpath 进
  `web.NavBar.SectionsMenu` / `web.NavBar`，而子节点的 role 是 **`web.DropdownItem` 全局共用组件**写死的
  —— 动它 = 动**所有**后台下拉（grep 实测：`menuitem` 出现在 318 个 XML 文件里）。爆炸半径不可接受。
- **键盘/读屏影响**（源码级事实）：`core/navigation/navigation.js` 与 dropdown/navbar 的 JS **没有任何一处按
  `[role=menu]` / `[role=menuitem]` 选择元素**（全仓 JS 里只有日历的 `tr[role=row]` 与一个 SCSS
  `[role=button]`；其余命中都在测试文件里）。所以这两个 role **纯属声明**：去掉不会改变任何键盘行为，
  保留也不会带来 APG 菜单语义（`.o_menu_sections` 并不实现方向键漫游）。
  ⇒ 「声明了 menu 却没有菜单键盘行为」本身就是**该不该保留**的开放问题，但改它属语义改写，不在本轮范围。
- 另：`aria-required-parent` 的**大头不是导航栏**。表单页上 5 条里 **0 条在导航栏**：那是核心
  `web/static/src/core/notebook/notebook.xml` 写死 `role="tab"`、外层 `ul.nav-tabs` 却没有 `role="tablist"`
  （Bootstrap 的 `tab.js` 本会自动补 `role=tablist`，Owl 版重写了那条路径所以没补）。
  **上一轮「aria-required-parent 属 NavBar 的 role=menu 结构」这条归因不完整**，以本节实测为准。

### 12.4 窄视口：label 修复在小屏的**真实**边界（tests/smoke/a11y_narrow_viewport_probe.py）

| 视口 | 后台形态 | 选择框 | 读数 |
|---|---|---|---|
| 390×900 | small：品牌 0 / 区段 0 / 汉堡 1 / menuitem 0 / role=menu 1 | **0** | **结构性 N/A**（见下） |
| 767×900 | 同上（isSmall 边界） | **0** | **结构性 N/A** |
| 768×900 | 非小屏：区段回来了 | **81** | **几何位移 0 ｜ PNG sha 完全相同**（清空 81 处可访问名前后） |
| 1280×900 | 桌面基准 | 81 | 几何位移 0 ｜ PNG sha 完全相同 |

- **为什么小屏是 N/A 而不是「验过了」**：`web/static/src/views/list/list_renderer.js` 的
  `get hasSelectors() { return this.props.allowSelectors && !this.env.isSmall; }`
  ⇒ **小屏根本不渲染选择列**，`.visually-hidden` 的可访问名自然也不存在。
  所以「窄视口下视觉零位移」这一问在小屏上是**结构性不适用**；真正能测的最窄宽度是 **768px**（isSmall 边界之上），
  那里实测零位移（几何 + 像素双向）。
- **后台小屏的实际形态**（core 模板条件 + 实测复核）：`ui.isSmall`（`MEDIAS_BREAKPOINTS`，≤767px）时
  `web.NavBar` **不渲染** `.o_menu_brand` 与 `.o_menu_sections`，改渲染
  `<a class="o_menu_toggle">` 汉堡；应用菜单换成 portal 到 `body` 的 `.o_app_menu_sidebar` 侧边栏
  （默认不开，点击才挂载）。
  **影响面**：① 12.3 那两类 navbar 违规在小屏上**自然消失**（sections 与 brand 都不在了），
  只剩 systray 的 `aria-required-children`；② 小屏**没有多选**（`hasSelectors=false`），
  所以 81 个 checkbox 的 label 问题在小屏上不存在。

### 12.5 违规归属分流：**按元素来源，不按规则名**（2026-09-29 队长批准；判据**只会更严**）

- **它治什么**：`/odoo/batches` 的 `button-name x17` 来自 **`custom_addons/edu_portal/views/class_batch_views.xml`**
  的 `<button name="action_edu_stop" type="object" icon="fa-pause-circle-o" title="停用（…）"/>`
  —— **我们自己的视图**声明的按钮（核心只负责把它画出来），却因规则名在 `CORE_RULES_KNOWN` 里被归进
  「核心渲染·只读数」。本仓吃过一次这种豁免的亏（一条 carve-out 让一个紫胶囊活了几个月：
  既没人修、也永远不再报警）⇒ 改判据。
- **机器可判定**：`custom_addon_buttons()` 直接扫 `custom_addons/**/*.xml` 里
  `<button … name="…">` 的名字集合（**不是人肉白名单**）；页面违规节点带 `elem_name`
  （`BACKEND_PROBE_JS` 逐节点取 `getAttribute('name')`）∈ 该集合 ⇒ **判据**；否则才是核心清单。
  刻意**不**扫 `<field name=…>`：字段名（active/name/code…）核心与自研大量重名，
  拿它判来源会把核心的锅算到我们头上（正是上一版一刀切的反向错误）。
- **端到端证据（改前/改后同一命令）**：`/odoo/batches` 判据 **0 → 17（critical）**，
  核心清单 **38 条/5 种 → 21 条/4 种**；同时 `/odoo/apps` 的 `button-name x18`（核心搜索面板按钮）
  **留在**核心清单 ⇒ 两个方向都被实测钉住（自研的翻红、核心的没被误伤）。
  门禁退出码 **0 → 2**（超出基线报警）。
- ⚠ **本轮留下的红**：那 17 条要修在 `custom_addons/edu_portal/views/class_batch_views.xml`
  （给该 `<button>` 补 `aria-label`，或改用 `string=` 出文字）。该文件**不在本轮可写范围**
  （另一个 agent 在动 edu_portal）⇒ **如实上报，不用放宽口径把它变绿**。
- 自证：`--selftest` 从 36 条加到 **39 条**，新增三条正是这个分流（自研⇒判据 / 核心⇒只读数 /
  按钮名集合确实是从仓内 XML 扫出来的）。
- ⚠ 改判据时的**手滑代价**（本轮踩到）：`BACKEND_PROBE_JS` 是 Python 里拼出来的 JS，
  第一版少一个右括号 ⇒ 浏览器 SyntaxError ⇒ **全部后台样本 INCOMPLETE（exit 3）**。
  现在 `mapV` 单独成常量，改完用 `node --check` 验过再跑门禁。

### 12.6 顺手修掉的一条「尺子自己坏了」（影响面比本任务大）

`a11y_ax_tree_probe.py` / `a11y_label_dom_compare.py` / `a11y_label_fix_experiment.py` 的就绪探针
用的是 module 级 `requests.get`，会被 **macOS 系统代理**（`scutil --proxy`: 127.0.0.1:12450）带走
⇒ 探本机 `/web/login` 反而拿 **502** ⇒ 三把尺子**全部 exit 2 ENV**（ENV 不当通过 ⇒ 一个读数都拿不到）。
`scripts/check_accessibility.py` 的 `site_ready()` 早就写明这条纪律（`trust_env=False`），三把尺子漏了。
已按同款修法补 `probe_session()` 并实测跑通（AX 树：81 checkbox / 无名 0）。


### 12.7 三把尺子逐页读数扫出来的**第二族无名 checkbox**（核心 `formatters.js`，本轮只上报未修）

三把尺子对 7 页各跑一遍（读数逐页见报告；工具：`a11y_ax_tree_probe.py` / `a11y_label_dom_compare.py` /
`a11y_label_fix_experiment.py`）：

| 页面 | 尺子1 AX 树 checkbox / **无名** | 尺子2 DOM 选择框 / 空 label | 尺子3 注入→修补 |
|---|---|---|---|
| /odoo/contacts | 81 / **0** | 81 / **0** | 注入 19 条（2700px 63 条）→ 修补后 **0** ✔ |
| /odoo/students | 0 / 0（看板） | 0 / 0 | N/A（无选择列） |
| /odoo/batches | 35 / **17** | 18 / **0** | 注入 → 修补后**仍有 17 条 / 仍匿名 17** ⇒ **FAIL** |
| /odoo/apps | 0 / 0（看板） | 0 / 0 | N/A |
| /odoo/contacts/1 | 3 / 0（「是一名家长/是一名学生/场地」） | 0 / 0 | N/A |
| /odoo/students/5 | 0 / 0 | 0 / 0 | N/A |
| /odoo/grade-configuration | 8 / **0** | 8 / **0** | N/A |

- **/odoo/batches 那 17 个匿名 checkbox 不是选择框那一族**：尺子2 证明 18 个选择框的 label 全部非空，
  尺子3 证明「补 .visually-hidden」修法对它们**无效**（修补后仍 17 条）⇒ 它们是**布尔列单元格**：
  核心 `web/static/src/views/fields/formatters.js` 把布尔列表单元格渲染成
  `<input id="boolean_checkbox" …><label for="boolean_checkbox"/>` —— **id 写死**，17 行同一个 id
  ⇒ `<label for>` 只能关联到第一行，其余无名。
- **能不能修（在我们自己的模块里）**：**不能**。那段是最小化的 HTML **字符串**（JS 拼出来的），
  **不是 Owl 模板** ⇒ `backend_debrand.xml` 的模板继承够不到它。
  可选路子两条，都超出本轮范围：① 上游（核心）修那个写死的 id；② 视图侧改用别的 widget
  （`widget="boolean_toggle"` 之类），但那是 `custom_addons/edu_portal/views/class_batch_views.xml` 的事
  —— 与 12.5 那 17 条 `button-name` **同一个文件、同一个 owner**，合在一起派一次即可。
- 判据口径：门禁里 `label`/布尔列这一族目前**只读数**（元素本身没有 `name`，
  按 12.5 的分流它不属于「自研视图声明的按钮」）—— 也就是说**门禁还没把这 17 条算成我们自己的账**，
  而尺子1/尺子3 已经证明它是**真实的无名控件**。要不要把它也纳入判据，是下一个决定。


### 12.8 后续（2026-09-29 傍晚，队长批准后）

**(a) 17 条 button-name：已修，但**不是**在视图里修的 —— 记下这条弯路**
- 先按授权在 `edu_portal/views/class_batch_views.xml` 的两个按钮上补了 `aria-label`，
  `safe_upgrade.sh edu_portal` 后**实测无效**：渲染出的 `<button>` 上**没有** `aria-label`。
  根因：`web.views.ViewButton` 的 `t-att="props.attrs"` 只展开**核心解析后保留的** arch 属性，
  这个属性在进 `props.attrs` 之前就被丢掉了（`title` 则被 §5.4 那行 `t-att-data-tooltip` 送进 `data-tooltip`）。
  ⇒ **该视图文件已 `git checkout` 还原**（另一个 agent 在动 edu_portal，不留脚印最好）。
- 改成**一处修一片**：在 `backend_debrand.xml` 继承 `web.views.ViewButton`，加一条
  `t-att-aria-label="props.string ? undefined : (props.title || undefined)"`
  —— **只在没有任何可见文字时**用 `title` 兜一个名字；有 `string` 的按钮一个都不碰
  （避免覆盖可见文字名，撞 WCAG 2.5.3 Label in Name）。
  实测：`/odoo/batches` DOM 上 `aria-label="停用（课表与历史保留，随时可恢复）"` 到位，
  `button-name 17 → 0`；判据（归属分流后）**17 → 0**，门禁 `--only <7 页>` 回到 **exit 0 / 在基线内**；
  同时 `/odoo/apps` 的 `button-name x18`（核心搜索面板折叠按钮，**不是** `ViewButton`）**纹丝不动**
  ⇒ 「修了一片、没碰另一片」两个方向都验了；7 页 console 报错仍为 0。

**(b) 布尔列那 17 个无名 checkbox：评估结论 = **不值得换**，登记为「我们模块内修不了」**
队长点名要先只读核查「换 `boolean_toggle` 后教务看到的还是不是一个能直接勾的方块」。**答案：反了，而且换了也修不好**——
- **今天它就不是能勾的方块**：实测 DOM 是 `<input type="checkbox" class="form-check-input" disabled="" checked="">`
  —— **disabled**（列表不可编辑，改状态要走「停用 / 恢复」按钮或进表单）。
- 换 `boolean_toggle` 反而**把它变成可点**（`web.ListBooleanToggleField` 包了一层 `t-on-click="onClick"`）
  ⇒ 17 行变成**列表内直接改状态**，那是**功能变更**，不是形态微调 ⇒ 按队长给的判据**停下报告，不换**。
- **换了也不解决可访问名**（源码级）：`web.BooleanToggleField` 以 `t-inherit-mode="primary"` 继承 `web.BooleanField`，
  只改了 className 与**塞了一个零宽空格**进 CheckBox 槽；而 `web.BooleanField` 本身是
  `<CheckBox …>` **不带任何 slot 内容**，`web.CheckBox` 的名字**只**来自那个 slot
  （`<label t-att-for=…><t t-slot="default"/></label>`）⇒ 换过去名字仍然是空的（一个零宽空格当名字）。
  ⚠ 零宽空格会不会让 axe 的 `label` 规则**闭嘴**（`'\u200b'.trim()` 在 ES 里不为空）**本轮未实测** —— 若真会，
  那换 widget 就是**用假绿换一个功能变更**，更要不得。**未实测这一点，不得当结论用。**
- **修不了的位置（上游）**：真正产出这 17 条的是 `web/static/src/views/fields/formatters.js`
  的只读布尔列表格式化器（`id="boolean_checkbox"` **写死** + 一个空 `<label for>`）；
  同型的交互路径在 `views/fields/boolean/boolean_field.xml` + `core/checkbox/checkbox.xml`。
  两处都是 **JS 拼的字符串 / 无 slot 的核心组件** ⇒ `backend_debrand.xml` 的 Owl 模板继承**够不到**。
  要在我们这一层消掉，只能改用户看到的东西（换 widget / 改可编辑性 / 改用文字列），那需要教务点头 —— 本轮**不做**。

**(c) `scripts/ui_surface_report.py` 的 `EXTRA_ROUTES` 补了 5 条 + `--generate` 实测**
- 补了 `/odoo/batches`、`/odoo/apps`、`/odoo/contacts/1`、`/odoo/students/5`、`/odoo/grade-configuration`。
- `python3 scripts/ui_surface_report.py --generate` 实测：**5 条全部保留 status=unverified + gates=accessibility（没有被降级成 ghost/gap）**；
  语义对拍（生成前后各 308 条）：`gates` 变化 0 条、`key` 变化 0 条、`roles` 变化 0 条、条目增删 0 条
  （215/215 行的 diff 是**纯重排**，生成器按 path 排序）。**再跑第二次 --generate 零 diff（幂等）**。
- 之后 `check_ui_surface.py` exit 0、`check_accessibility --list` 取样仍是 66 页（43 条登记）—— 覆盖没变大也没变小。

**(d) 豁免没有把门禁变成哑巴（队长点名必做，已做）**
向 `tests/ui/surface.json` 注入一条**真的失效**的登记（`/odoo/stale-probe-should-fail`：既不在 `custom_addons` 的
`@http.route` 里，也不在 `ALLOW_NO_ROUTE` 里）⇒ `check_ui_surface.py`
**exit 1**，逐条打印 `FAIL 登记已失效：/odoo/stale-probe-should-fail（pages[308]）`；
还原后 exit 0、违规 0 条。**证据**：注入前后各跑一次，命令与读数见本轮报告。
