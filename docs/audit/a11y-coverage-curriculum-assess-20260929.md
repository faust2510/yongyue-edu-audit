# 无障碍门禁：补两处覆盖 + 「还能红」演练（2026-09-29）

> 采集时刻：**2026-09-29 21:0x–21:2x（Asia/Shanghai）**，本地 edu19，axe 4.10.2，Chrome headless 1280x900。
> 门禁自证：`REVISION=a5 · 指纹 bcae4446 · 断言 39 条`（指纹随文件改动变，引用时请连自证头一起贴）。
> 复跑：`python3 scripts/check_accessibility.py --list` / `python3 scripts/check_accessibility.py` /
> `python3 tests/smoke/a11y_gate_red_rehearsal.py`

---

## 0. 干了什么

| 项 | 内容 |
|---|---|
| **A. 补一处「完全没有门禁」的页** | `/registrar/curriculum`（教务天天用的**课程编排页**）原在 `tests/ui/surface.json` 里 `gates=[] / status=gap` ⇒ **三张 UI 门禁没有一张扫它**。本轮把它登记进表（只加 `accessibility`），并在 `AUDIT_ROUTES` 里给它**教务专属取样身份** |
| **B. 补一处「取样身份不够」的页** | `/assess` 原先**只取 student 一个身份**，而「整班打分」卡片挂在 `can_grade = 教务组·系统组 ∪ 教师组` 上 ⇒ **那张卡的渲染路径结构上不可能被学生身份扫到**。`/assess/review` 同样只有 faculty。本轮各补身份 |
| **C. 证明「真的被扫到」** | 定向重扫 + 全量重扫，逐条打印 `role path` 与规则集合 |
| **D. 证明「还能红」** | 新增注入演练器 `tests/smoke/a11y_gate_red_rehearsal.py`：**运行时**建一条临时 `ir.ui.view` 把违例元素插进目标渲染路径 ⇒ 门禁必须变红 ⇒ 删掉 ⇒ 必须回绿。**课程编排 7/7 PASS，测评门 16/16 PASS** |
| **E. 如实报扩覆盖的读数** | **没有扫出任何新违规**（70/70 页 × 0 条）。这一条不是「加豁免换来的绿」，理由见 §4 |

---

## 1. 为什么这两处是**实测缺口**（不是「可能漏」）

### 1.1 `/registrar/curriculum`

- 它是 `custom_addons/edu_portal/controllers/enroll.py` 的
  `EduCurriculumPortal.curriculum` / `EduCurriculumPortal.curriculum_save`
   —— 教务选专业 → 列该专业科目 → 逐行/批量标「必修 / 选修」的页面（2026-09-29 刚加了批量控件）。
- 表里它的登记是 `gates=[]`、`status=gap`，`reason` 写着
  「三个门禁均未登记该路由（口径：路径精确匹配）：自助服务页 / 其它内容页」。
- `scripts/check_accessibility.py` 的 `AUDIT_ROUTES` 里**也没有它**
  ⇒ 扫描面 = 「表里 gates 含 accessibility」∩「有可用取样身份」= **空集**。
  ⇒ 它写的任何无障碍问题**没有任何门禁能发现**。
- 该组自己写过一把尺子 `tests/smoke/curriculum_a11y.py`（AX 树 + 键盘可达 + axe），
  但**那不是站点门禁**，不进 `check_accessibility.py` 的读数，也没有基线漂移报警。

### 1.2 `/assess` 与 `/assess/review` 的取样身份

- `edu_assess/controllers/portal.py` 的 `assess_home`：
  `can_grade = _is_school_admin() or _is_teacher()`，
  「整班打分」卡片是 `views/assess_portal.xml` 里 `<div class="col" t-if="can_grade">` 那一段。
- 表里 `/assess` 的 `roles` 本来就有 `admin/backoffice/faculty/student`，
  但 `AUDIT_ROUTES` **只给了 `('student', '/assess')`** ⇒ **学生身份看不到这张卡**
  ⇒ 卡片的整条渲染路径（卡片 HTML + 「进入整班打分」按钮 + 两句空态 + 计数）**从未进过站点门禁**。
- `/assess/review` 的门禁是 `教务组·系统组 ∪ 教师组`（`assess_review`），
  而 `AUDIT_ROUTES` 只给了 `faculty` ⇒ **教务那条渲染分支也没样本**。

---

## 2. 改了哪几行（三处，都是加法）

| 文件 | 改动 |
|---|---|
| `tests/ui/surface.json` | `registrar_curriculum` 这一条：`gates: [] → ["accessibility"]`、`status: gap → unverified`、`reason` 清空（原文搬进 `evidence` 存档）。**其余条目一行未动**（另一 agent 删 `/eval/*` 的改动是他们的，未触碰） |
| `scripts/check_accessibility.py` 的 `AUDIT_ROUTES` | 追加 4 条：`('backoffice','/assess')`、`('faculty','/assess')`、`('backoffice','/assess/review')`、`('backoffice','/registrar/curriculum')`，每条带「为什么原先没覆盖」的实测理由 |
| 同上（文档字符串 / 打印行） | 把写死的「公开 6 + 学生 8 + 教师 6 + 家长 4 + 教务 4 = 28 页」改成「**不在此写死分项**，逐条清单见取样集」（写死的读数会烂 —— code-map §6 第 15 条） |

**为什么 `/registrar/curriculum` 用裸路径而不是 `?course_id=N`**：
控制器在**未带 `course_id` 时默认落在第一个有科目清单的专业**（无参分支），所以裸路径就有内容；
挂上查询串反而会让取样路径与 `surface.json` 的登记路径**对不上账**
（`build_samples` 按字面路径比对 ⇒ 会被判成「口径里有、表里没有」而**不扫**）。

---

## 3. 「真的被扫到」——读数

### 3.1 名单口径（`--list`）

| 读数 | 改前 | 改后 |
|---|---|---|
| `surface.json` 指纹 | `34c4ffd8` | `e879af54` |
| 表里 `gates=accessibility` 登记条数 | 43 | **44** |
| 取样集（身份 × 路径） | 66 | **70**（口径 43 + 表新增 27） |
| 对账「取样口径路径 − 表」／「表 − 取样集」 | 空／空 | **空／空** |
| 覆盖缺口（登记了却没人扫） | 0 | **0** |

### 3.2 4 条新取样身份真的进了扫描集并渲染成功

定向重扫 `--only /assess,/assess/review,/registrar/curriculum`（**样本 70 → 6，不是全站口径**）：

    student     /assess                        OK
    faculty     /assess/review                 OK
    backoffice  /assess                        OK
    faculty     /assess                        OK
    backoffice  /assess/review                 OK
    backoffice  /registrar/curriculum          OK        ← 新增
    ================ 汇总 ================
    违规合计 = 0 条 ｜ 扫描成功页 = 6 / 6 ｜ 漂移判定：在基线内

### 3.3 全量门禁（改后，`2026-09-29T21:22:58+08:00`）

    == 取样口径：70 页 ==
    违规合计 = 0 条（critical 0 / serious 0 / moderate 0 / minor 0）
    扫描成功页 = 70 / 70
    基线 {"critical":0,"serious":0,"moderate":0,"minor":0,"total":0,"pages":70}
    漂移判定：在基线内
    退出码 EXIT=0

---

## 4. 「还能红」——注入演练（**这才是覆盖真的生效的证据**）

**工具**：`tests/smoke/a11y_gate_red_rehearsal.py`（本轮新增）

**它怎么注入**：在 odoo shell 里**运行时**建一条**无 xmlid 的临时 `ir.ui.view`**，
用 xpath 把两个独立违例（`<img>` 无 `alt` → `image-alt`；
`<button>` 里只有空 `<span>` → `button-name`）插进目标模板的指定锚点；
测完 `unlink`，并**逐字复核残留 = 0**、再跑一次门禁**必须回绿**。
**不改仓库任何文件、不跑 `-u` 升级、不动数据库既有内容。**

**为什么不用「改模块 XML + `safe_upgrade.sh`」那套**（`tests/smoke/UX_V3_GATE.md` §11.3 对后台页用的）：
`-u edu_portal` 会重放被 `edu_nav` 收口的菜单（**未关闭的 F1**，
`docs/audit/finding-F1-menu-replay-on-upgrade.md`）⇒ 会顺手改掉别的 agent 正在依赖的状态。
运行时建视图**立刻生效**（配合 §5 的 `signal_changes`），不需要升级锁、不重启容器。

### 4.1 课程编排页 `/registrar/curriculum`（`--target curriculum`）**7/7 PASS**

    基线（注入前）：{"backoffice /registrar/curriculum": []}                       exit=0
    [inject] 模板 edu_portal.edu_registrar_curriculum | xpath //h4[hasclass('mb-0')] | view_id=3739
    注入后：{"backoffice /registrar/curriculum": ["button-name", "image-alt"]}      exit=2  ★ 变红
    变红身份=['backoffice']（预期 ['backoffice']）
    复原：残留=0；复原后 {"backoffice /registrar/curriculum": []}                   exit=0  ★ 回绿

### 4.2 `/assess` 的「整班打分」卡片（`--target assess`）**16/16 PASS**

    ★ 注入前逐身份直读 /assess（12 次请求 × 3 个身份，全部 200）：
        backoffice 标记命中 0 / faculty 命中 0 / student 命中 0
    [inject] 模板 edu_assess.edu_assess_home | xpath //div[@t-if='can_grade'] | view_id=3746
    ★ 等待注入生效（逐身份，连续 3 轮 × 12 次全部一致）：
        backoffice ok=True(3.8s) ｜ faculty ok=True(3.2s) ｜ student ok=True(2.9s，命中数恒为 0)
    ★ 注入后门禁逐页规则：
        {"student /assess": [],
         "faculty /assess/review": [],
         "backoffice /assess": ["button-name","image-alt"],   ← 变红
         "faculty /assess": ["button-name","image-alt"],      ← 变红
         "backoffice /assess/review": []}
        exit=2
    ★ 变红只发生在预期身份上：实际 ['backoffice','faculty'] ｜ 预期 ['backoffice','faculty']
    ★ 对照身份 student **没有**新规则 —— 证明那张卡本就只在教务/教师身份上渲染
    复原：残留=0；复原后逐页规则与基线**逐字相同**，exit=0  ★ 回绿

> **这一组读数同时证明了两件事**：
> ① 「整班打分」卡片的渲染路径**现在真的在门禁覆盖内**（注入进去立刻被 axe 抓到）；
> ② **原先只有 student 身份时，这张卡的缺陷结构上不可能被发现**（同一个注入，student 身份 0 违规）。
> 这正是补身份要治的那个假绿形态。

### 4.3 注入演练没扫出问题时**不许当通过**

演练器的判据是**双向**的：注入后必须变红**且**变红的原因必须是「本页出现了注入前没有的 axe 规则」；
复原后必须回绿**且**逐页规则与基线**逐字相同**。任一条不成立即 FAIL（退出码 1）。
每一条读数（含每次请求的 marker 命中序列、耗时）都落盘到
`tests/smoke/a11y_gate_red_rehearsal_results.json`。

---

## 5. 两个实测坑（**不修就会得到自相矛盾的读数**，都写进了演练器注释）

### 5.1 本栈 odoo 是 `workers=6`（`config/odoo.conf`）

六个 worker **各自持有自己的 registry / qweb 模板缓存**，而 HTTP 是轮询分发
⇒ 「打两个请求都看到新内容」**不等于**「6 个 worker 都更新了」。
更阴的是 `requests.Session` 默认 keep-alive，会把同一个连接**钉在同一个 worker** 上
⇒ 探针自己在给自己报假平安。
**首版实测形态**：同一页 36 次请求的 marker 命中序列是 `T/F` 交错，150 秒不收敛。
**修法**：`Connection: close` + 每轮 12 次请求（> workers）+ 连续 3 轮全部一致才算稳定。

### 5.2 跨进程失效**不是**数据库触发器，是 RPC 分发时喊一声

- `odoo/orm/registry.py` 的 `Registry.signal_changes()` 往
  `orm_signaling_<cache>` 插一行通知别的进程；
- 它只在 **RPC 分发**结束处被调用（`odoo/service/model.py` 的 `dispatch`）；
- **`odoo shell` 走的是直接 ORM + `cr.commit()`，从不经过 `dispatch`**
  ⇒ 别的 worker **永远收不到通知**，只能靠 ormcache 的 LRU 随机淘汰偶尔看到新 arch
  —— 这既是 §5.1 那个交错序列的**根因**，也解释了一整类「我在 shell 里改了，页面没变」的困惑。
- **修法**：改完显式 `env.registry.signal_changes()` 一次。
  加上它之后，同一探针的命中序列变成 **24/24 全 T × 3 轮**（秒级稳定）。

> ⚠ 这两条对**任何**「在 `odoo shell` 里改数据/视图、然后从 HTTP 侧验证」的探针都成立，
> 不只是本演练器。反过来说：**正式升级（`safe_upgrade.sh`）不受影响** ——
> 它会让 worker 重新起来，缓存天然是新的。**这只坑「带外改动」。**

---

## 6. 扩覆盖的读数：**没有扫出新违规**（如实报，且不是豁免换来的）

用户口径是「扩覆盖**预期会扫出既有违规**：如实报出总数与逐条清单」。
**实测：portal 侧 0 条。** 唯一非零的是**后台页的核心渲染清单**（75 条 / 7 种规则），
它按门禁既定纪律**只读数、不计入判据**，且**基线已钉在 0**：

    核心渲染清单（Odoo 核心渲染，不在本仓可改范围）：规则 7 种 / 节点 75 条
      label                    critical x18   页面主体(核心渲染)
      button-name              critical x18   页面主体(核心渲染)
      aria-required-parent     critical x12   外壳(核心结构)
      aria-required-children   critical x11   外壳(核心结构)
      aria-allowed-attr        critical x11   页面主体(核心渲染)
      role-img-alt             serious  x4    页面主体(核心渲染)
      color-contrast           serious  x1    页面主体(核心渲染)
    判据（零容忍，计入基线）：0 条 ｜ 其中本地对比度 = 0 条

**为什么这个「0」值得信**（三条，缺一不可）：

1. **扫描面确实变大了**，不是「统计口径变松」：取样 66 → 70，去重路径 66 → 70，
   表登记 43 → 44，对账两个方向都是空集，覆盖缺口 0。
2. **这两页的渲染路径此前就被该组自己的探针量过**
   （`tests/smoke/curriculum_a11y.py`、`tests/smoke/assess_home_grade_entry.py`）——
   本轮做的是把**同一批渲染路径接进站点门禁**，所以「本来就没违规」是可信的结果，不是「没扫到」。
3. **§4 的注入演练证明这把尺子在这两条路径上量得动缺陷**：
   同一个页面、同一个身份，注入两个违例立刻变红（`button-name` + `image-alt`），
   删掉立刻回绿。**没有这一条，§6 的「0」就只是「没红」而已。**

**没做任何加豁免 / 放宽基线 / 塞白名单的动作**：`BASELINE` 常量一行未改
（仍是 `{"critical":0,"serious":0,"moderate":0,"minor":0,"total":0}`），
`SHELL_RULES_KNOWN` / `CORE_RULES_KNOWN` / `BACKEND_EXPECT_VIEW` 一行未改。
唯一的放宽机制是 `BASELINE['pages']` 随当轮取样集写入（脚本原有逻辑，且 `comparable` 守卫
会把「页数不够」判成不可比 ⇒ 不判绿）。

---

## 7. 没做成 / 不确定的部分

1. **没有跑 `curl` 之外的真实浏览器会话之外的层**：`/registrar/curriculum` 的
   **键盘可达**（Tab/Space/Enter 走完批量动作）只由该组自己的 `curriculum_a11y.py` 量过，
   **本站点门禁的扫描面只有 axe**，不覆盖键盘。这是门禁口径的已知边界，不是本轮引入的。
2. **`/assess/tasks` 等 5 个 `表新增` 条目**仍只按 `roles` 自动补样，
   本轮的注入演练**只覆盖了 `/assess` 与 `/registrar/curriculum` 两条**，
   其余页面「还能红」未逐页演练（工作量线性增长，本轮按用户点名的两处做）。
3. **`/assess/grade/<int:task_id>`（整班打分的真正落点）仍是 `dyn` 行**，
   靠「上级继承」覆盖，**不被裸探**。本轮的注入证明了卡片（入口）在覆盖内，
   **但没有证明矩阵页本身在覆盖内** —— 那需要样本 id + 专门的夹具，属另一件事。
4. **没有把本轮读数写进 `tests/smoke/UX_V3_GATE.md`**（该文件由别的口径维护，不在本任务可写范围内的「新增探针」里）。
   如果维护者要，建议追加 §13「门户侧身份缺口 + 注入演练器」并回指本文件。
5. **注入演练器会短暂建一条 `ir.ui.view`**（无 xmlid，测完即删，残留逐字自证 = 0）。
   若演练中途被强杀，用 `python3 tests/smoke/a11y_gate_red_rehearsal.py --restore` 清场。
   本轮全部运行结束时残留均为 0（读数落 JSON）。
6. **演练运行期间会往 odoo shell 起独立进程**（约 8–20 秒/次），
   在别的 agent 也在跑升级/门禁时可能互相影响；演练器检测到 `edu19_upgrade.lock` 会直接 ENV 退出（不当通过）。
