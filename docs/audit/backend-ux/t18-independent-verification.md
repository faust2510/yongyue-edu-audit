# task-18 独立验证清单（backend-ux 出具，全部只读）

> 验证人：teammate `backend-ux`（**不是** task-18 实现的作者）｜日期：2026-10-03
> 被验对象：commit `415d215`（`custom_addons/edu_portal/controllers/grading.py` + `controllers/__init__.py` 的导入 + 两个探针文件）
> 验证脚本：`/tmp/verify_t18.py`（**我自己写的**，不复用作者探针的判据）｜结果：`t18_independent_verification.json`
> 结论：**11/11 PASS**，四条待验 claim 全部成立。

---

## 0. 先说清我的立场与边界

- 我是**独立验证方**，不是实现方。作者的探针 `tests/smoke/gradebook_registrar_entry.py` 的 20/20
  我只当**旁证**，不当证据本体 —— 因为「用作者自己的尺子量作者的活」有两类系统性风险：
  ① 判据写错时自己发现不了；② 判据与实现一起错(同一处误解)。所以我另写了一把尺子。
- 我在验证过程中**没有修改任何一行实现代码**（见 §5 的文件完整性）。
- 写路径的验证必须 POST 一次分数，我**改前/改后各读一次库**，并在结束时**还原原值**（§3）。

---

## 1. claim ①：教务在 /grade-book 上看到的是录入形态（不是拒止文案）

判据落在**渲染后的页面**（Playwright，1440×1000，真浏览器）：

| 身份 | HTTP | 页面 title | 有班级下拉 `#ge-batch` | 含拒止文案 | 判定 |
|---|---|---|---|---|---|
| backoffice（教务） | 200 | **成绩录入** | **是** | 否 | ✅ 录入形态 |
| admin（超管） | 200 | **成绩录入** | **是** | 否 | ✅ 录入形态 |
| faculty（教师） | 200 | 成绩簿 | 否 | **是** | 拒止（未变） |
| parent（家长） | 200 | 成绩簿 | 否 | **是** | 拒止（未变） |
| 未登录 | 200 | Login · 永约学坊 | 否 | 否 | → `/login?redirect=%2Fgrade-book%3F` |

**这把尺子有区分力（不是恒绿）**：同一个 URL、同一个时刻，只因身份不同就得到两种结果；
而且「拒止文案」这个检测器**在教师/家长身上确实命中了同一个字符串** —— 说明它不是匹配不到而报绿。

## 2. claim ②：学生端 /grade-book 未被改动（分流是按身份，不是全局替换）

- 学生账号 `stu@local` 打开 `/grade-book`：title = **成绩簿**，服务端渲染的 HTML 里
  **不含** `yy-grade-matrix`（录入页的矩阵钩子）⇒ 学生拿到的仍是原来的成绩簿。
- 作者的探针 C5 断言同向，但那是**旁证**；本条是我用 requests 直读渲染结果独立得出的。

## 3. claim ③：教务在 /grade-book 这条线上录分 → 学生端随之变化（端到端闭环）

**我走的路径与作者探针不同**：作者用浏览器点表单，我用 requests 直接 POST 表单契约
（`action=/grade-entry/save`，字段 `csrf_token` / `batch_id` / `term_id` / `m_<student>_<subject>`，
契约读自 `views/grade_entry.xml`）。两条不同路径得到同一结论，可信度高于重复跑同一条。

| 步骤 | 读数 |
|---|---|
| 改前库内（写侧 attendee \| 读侧 result_line） | `74\|74` |
| 教务 uid | 12 |
| 从表单取 csrf_token | 成功 |
| POST `/grade-entry/save`（`m_5_35=91`） | **303** → `?saved=1&n=1` |
| 改后库内 | **`91\|91`**（两侧同步，不是只写一侧） |
| 学生端 `/grade-book` 服务端渲染 | 出现 **91**（数字单元格样例 `['91','100','61','100','92','100']`） |
| 学生端形态 | 仍是成绩簿（无 `yy-grade-matrix`） |

**还原**：把 `m_5_35` 写回原值 74 → 库内 `74\|74` → 学生端回到 74（样例 `['74','100',...]`）。

> ⚠ 注意：`result_line` 这一侧正是本仓历史上「教务录了、学生看不见」的断层所在
> （见 `docs/research/gradebook-entry.md` §3）。这里**两侧同时**变成 91，说明这条链是通的。

## 4. claim ④：未登录 → 登录页（不是 200 的业务页）

`/grade-book` 匿名访问 → 落到 `/login?redirect=%2Fgrade-book%3F`，**不渲染任何成绩内容**。
（判据用的是**最终 URL**，不是状态码 —— Odoo 这里返回的是 200 + 客户端跳转，只看状态码会误判成通过。）

---

## 5. 文件完整性：我碰过什么、没碰过什么

| 文件 | 我的动作 | 现状 |
|---|---|---|
| `controllers/grading.py` | 反向自证时**临时注入**一行（`if privileged_staff():` → `if False:`），随后 `cp` 还原 | `diff /tmp/grading.py.bak` = **IDENTICAL**；md5 `175158c157bed5ac30829b3fce3a09ab`（两边一致） |
| `controllers/__init__.py` | **只读**，从未写入 | 3 行新增 = 作者的 `from . import grading` + 注释 |
| `controllers/batch2.py` / `roles.py` | **只读** | 有未提交改动，但 `git diff` 里 grep `grade` 或 `成绩` = **0 行**，与本功能无关 |
| 数据库（batch 8 / subject 35 / student 5 的分数） | 写 91 → 还原 74 | 已回到 `74\|74`（§3） |

### 5.1 我的副作用（如实登记）

为跑反向自证我执行过 2 次 `bash scripts/safe_upgrade.sh edu_portal`（EXIT=0、无 Traceback）；
`safe_upgrade` 的固定收尾会**重启 web 容器**。连同此前 1 次正常升级，共 **3 次重启**，时间约 16:52–16:56。
若有其他队友的门禁在这个窗口被判 ENV／样本作废，账记在我这里。

---

## 6. 旁证（不作为证据本体）

- 作者探针 `tests/smoke/gradebook_registrar_entry.py`：**20/20 PASS，exit 0**（我复跑 2 次，改前/改后各一次）。
- 该探针自带还原段（R1–R4），我确认跑完后库内为 `74\|74`、演示行 `EX-DEMO-01` 未变。

## 7. 未决 / 提请裁定

1. **教师 `/grade-book` 仍是拒止页**（同一 URL），教师另有「学习 → 成绩录入」入口。
   我的核验把这一条记为「原行为未变」，但**它本身是不是期望行为，需要用户拍板**：
   同一条「成绩簿」入口对教师仍然是一次死路（只是死法从「拒止」变成「拒止」）。
2. 教务可**覆盖**已有分数（我把 74 改成 91 成功了）。是否需要「只能录空、不能改」或「改需理由」，见回报正文的待确认项。
3. 本探针**未接进 `scripts/check_all.sh`** —— 该脚本用显式 `run "名字"` 注册，
   现有的 `grade_entry_probe.py` 也同样没注册。仓内自己的话：「门禁再多，不跑就等于没有」。
   （`scripts/` 不在我的写作用域，故只报不改。）
---

## 8. 附：`check_all.sh --fresh-install` 那 3 项红的归因（Lead 交办，全部只读复跑）

首次跑（16:57–17:01，与我的 3 次 web 重启同窗口）：**通过 30 / 失败 3**。
逐项单独复跑后：**3/3 全绿**，且我找到了每一项的确切机制。

| 项 | 首跑 | 单独复跑 | 归因 | 是否与 task-18 有关 |
|---|---|---|---|---|
| `ui_usability` | exit 2 | **exit 0**（命中 0 条 / 报红 0 页） | 首跑期间正逢 web 容器重启（见 §5.1）⇒ 采样被打断 | **否**（它只扫 `surface.json` 里 `scope==portal` 的页；`/grade-book` 登记为 `scope=other`，不在其名单内） |
| `metric_consistency` | exit 1 | **exit 0**（RESULT=OK，各指标极差 0.00） | 首跑红在「导航到 `/my/checkins` 超时」＝ edu_life 页面加载被打断，同一原因 | **否**（不是我的路由，也未被本次改动触及） |
| `fresh_install` | exit 2「ENV：建库失败」 | **exit 0**（全新库装得上，7 个关键模块 installed，到堂打卡类型在） | 见下方机制复现 | **否** |

### 8.1 `fresh_install` 的「建库失败」到底是什么（**不是部署阻塞**，但值得单独开卡）

Lead 特别点名这条「若是真的是部署阻塞级」。结论：**不是** —— 全新库安装本身**是通的**（复跑 exit 0）。
红的是 `scripts/check_fresh_install.sh` 的**清理/建库两步在并发下不幂等**。

脚本原文（`scripts/check_fresh_install.sh`）：

```bash
$DC psql -U odoo -d postgres -c "drop database if exists $DB;"   >/dev/null 2>&1
$DC psql -U odoo -d postgres -c "create database $DB owner odoo;"  >/dev/null 2>&1 || { echo "ENV：建库失败"; exit 2; }
```

**我把这个失败态在独立库名上复现了出来**（不碰 `edu19`）：

```
1) 先建好库（模拟上次跑剩的 edu19_rehearsal）
2) 在库里挂一个活动连接（模拟上次的 odoo 容器还没退干净）
   edu19_probe_bx 上的连接数: 1
3) 照脚本两步做：
   ERROR:  database "edu19_probe_bx" is being accessed by other users
   DETAIL: There is 1 other session using the database.
   drop rc=1
   ERROR:  database "edu19_probe_bx" already exists
   create rc=1                <- 脚本把 stderr 吞了，只报「建库失败」
```

**机制**：只要上一次的演练库 `edu19_rehearsal` 还在、且**还有任何一条活动连接**（上一次的
一次性 `odoo` 容器没退干净，或两次检查并发跑），`DROP DATABASE` 就会因「被其他会话占用」失败；
紧接着 `CREATE DATABASE` 因「已存在」失败 ⇒ 报「建库失败」。
**真正卡住的是 DROP，不是 CREATE** —— 而脚本 `>/dev/null 2>&1` 把真实的 PG 报错吞掉了，
所以给出的诊断信息会把人往「建库权限/磁盘」方向带（本次我自己就先怀疑了这两条）。

**建议（`scripts/` 不在我的写作用域，故只报不改，交 Lead 派卡）**：
1. `DROP DATABASE ... WITH (FORCE)`（PG 13+，本机 PG16 支持）；或先
   `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=$DB AND pid <> pg_backend_pid();`；
2. **不要吞 stderr** —— 把原始 PG 错误打出来，否则每次都要重新推理一遍；
3. 并发安全：演练库名带 PID/时间戳（`edu19_rehearsal_$$`），从根上避免两次检查撞同一个名字。

### 8.2 归因口径声明

「单独复跑绿了」**不等于**「首跑那次是环境问题」—— 我用了两条独立证据来排除：
① `ui_usability` 的名单里根本没有 `/grade-book`（`scope=other`），改动面与它不相交；
② 三项的失败形态都是**连接被掐断/资源被占用**（导航超时、建库被占用），
   而不是**断言失败** —— 若判据真的红，复跑不会变绿。
外加 §5.1 那条时间窗自认：三次 web 重启与首跑窗口重叠。