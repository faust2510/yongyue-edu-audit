# v3 改造 · t9 独立验证报告
> **状态**：`归档` ｜ **主题**：`v3 改造验证` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 验证者：verifier（独立执行，**不复用实现者自述**；凡引用他人证据均标注来源与等级）
> 时间：2026-09-12 13:41–13:46（稳定窗口 `SAMPLE_VALID`：无锁 / web Up 65s→231s 无重启 / 带 cookie 探活 `/web/login?db=edu19`=302）
> 工具规范：`tests/smoke/UX_V3_GATE.md`（467 行）；本文只写"命令 → 实际输出 → 结论"。
> 环境：本地 edu19 @ localhost:8069（`db_name = edu19` + `list_db = False`）

> **⚠ 本文是 2026-09-12 13:41–13:46 的历史读数快照**（工具输出逐字留档，**不改写**）。
> **2026-09-14 t110 逐行复核**发现 **8 处此后发生的漂移或推翻**，就地标注如下（行号为复核时行号）：
> 1. `:5` 工具规范 `UX_V3_GATE.md` 行数 **467 → 573**（`wc -l`）。
> 2. `:14` / `:38` check_odoo_trace 口径 **「50 条静态路由」→「52 条静态路由 + 动态发现」**，并已升为**四维 + 邮件数据面**（可达/不可达登记见 §10、§21）。
> 3. `:45` check_english selftest **24 项断言 → 43 项**，REVISION **v3.6**。
> 4. `:84`–`:90` 矩阵与看板：**WARN 3 → WARN 0 / PASS 500**（t110 复跑）；`/my/checkin/board` **已修（t104）**，`edu_portal.edu_welfare_board` **已定义于 `views/welfare.xml`** —— **「全仓零定义」已被修复推翻**，本段保留作历史。
> 5. `:71`–`:72` 根因引用的行号已漂移；映射字典**现位于 `controllers/downloads.py:209-215`，且已含 `'activate': '资料批量启用'`**（t28 已修，收口见 §12）——「缺键」不再是现状。
> 6. `:57` must-fix 的**来源标注**：该行现为按钮组（含 `value="activate"` 恢复按钮），映射字典位置同上。
> 7. `:116` M3 首页高度读数：后续实测为 **1436 / 1504 / 1519**（见 §3.6）⇒ 本表是 13:4x 快照，不是最新值。
> 8. `:174` `edu_audit_log=6`：**现为 5** —— 该计数随数据演进，**不是固定值**。
>
> **第二批复核（201–430 行）另有 9 处，同一性质**：
> 9. `:204`/`:211` 路由清单 **50 → 52 条静态路由**（+动态发现）。
> 10. `:209` odoo_trace selftest **10/10 → 17 扫描样本 + 11 规则族 + 4 退出码契约 + 7 数据不变量**（REVISION v3.6 / 断言 40）。
> 11. `:256`–`:258` §11 实证的 `res_partner(2).name = 'OpenEducat Bot'` **已由 t26 治根改名为「系统」**（见 §19）—— 该行是当时现状，非现状。
> 12. `:366`–`:375` §14.3「当前为 23 处待修」+`:423`–`:426`「check_odoo_trace 报 23 处」：**已闭环**（t29 视图隐藏 + t36 PO 覆盖，均 completed）⇒ 现全站 **brand 0 / trace 0 命中**；`:396`–`:397`「全量扫描会报 23 处属性级命中」同理**现为 0**（数据面口径见 §21）。
> 13. `:412`–`:419` brand **148**（faculty 75 / backoffice 73）：**现为 brand 0**（同上）。
> 14. `:384` odoo_trace selftest **13 个样本**、`:405` check_english selftest **26 项**：现分别为 17 个扫描样本 / **43 项**（v3.6）。
>
> **第三批复核（432–509 行）1 处，性质不同（机制被替换，不只是数字漂移）**：
> 15. `:465` 「`_via_managed_portal_path()` **调用栈判定**」：**实现已由 t42 换成 context 标记** —— 函数名未变，函数体现在是 `return bool(self.env.context.get('edu_marks_entry'))`（见 `custom_addons/edu_portal/models/exam_session_ext.py:41-53` 的 docstring）⇒ t35 提的**栈深脆弱性（>8 层或多包一层就漏判→双记）已消除**；引用该函数时请写「context 标记（t42 替换调用栈判定）」。
>
> **第四批复核（509–917 行，10 条）—— 其中 6 条是**渲染缺陷**（占位记号未替换进正文），已就地修好**：
> 16. `:604` / `:606` / `:619` / `:686` 的 `` [`] ``、`BTK`、`[[BT]]`、`[[/BT]]` 是**未替换的占位记号**（`BTK`＝反引号、`[[BT]]`＝加粗），渲染出来是乱码 ⇒ **已就地换成正常行内代码 / 加粗**；**全仓重扫确认占位记号仅这 6 行**（无一遗漏、无第二族）。
> 17. `:626` / `:627` 同上（`[[BT]]…[[BT]]` → 加粗）。
> 18. `:717` **§21.7 排在 §22 之后**（章节顺序错位）⇒ **未搬动正文**（改写历史比错位更糟），改为在 §21 末尾与 §21.7 标题处各加一条**位置说明**，**按编号读、不按位置读**。
> 19. `:545` §19 odoo_trace selftest「13/13 PASS」：现为 **17 扫描样本 + 11 规则族 + 4 退出码契约 + 7 数据不变量**（v3.6 / 断言 40）。
> 20. `:550`–`:557` §19「TECH_LOGINS 差异（latent）…建议对齐」读作待办：**t41 已对齐**（见 §21.1）。
> 21. `:724` / `:733` §21.7 自证行「v3.6 / 指纹 0461231c / **24 条**」：该指纹**正确绑定当时版本**（这正是"读数必须带版本"的用法）；**此后工具又改过（24 → 40 条）** ⇒ 引用时须**再绑当时的指纹**。
> 22. `:682` 前后 §19 的「**52 条静态路由**」**与现状一致**（列此以免与 F2/G1 的 50 混淆）—— **无需改**。
>
> **§27 增补（2026-09-14，verifier 独立复跑 —— 本文件里最新的一次 axe 读数）**：
> `2026-09-14T10:04:35 · 28/28 页 · 并发 quiet · 工具指纹 71953d4b（未改）` ⇒ **违规合计 384（critical 85 / serious 299）**，
> `color-contrast` **649 → 295**；其余规则未动（`select-name` 33 / `button-name` 25 / `label` 20 / `image-alt` 7）。
> **critical 仍 85 ＝ 基线里的 critical**，恰好印证 **B/C 组尚未开始**（A 组只动了颜色令牌）。
> ⚠ **`BASELINE` 常量仍是最初的 738 ⇒ 门禁在 384–738 区间对真回归失明**（本次复跑的结果就落在"在基线内"）——
> 已要求 A 组**每轮读数后立即把常量下调到该轮实测值**（只动数值、不动结构），使"变多即报"真正生效。
> **读数口径提醒**：本节与 §4（交付报告）里出现过的 **522** 是**更早的窗口**（A 组第一轮、页脚修复前）；
> 引用时以**带指纹与时刻的那一条**为准，不要把 384 与 522 混用。

---

## 结论速览

| # | 验证项 | 结论 | 关键证据 |
|---|---|---|---|
| 1 | Odoo / 基座品牌痕迹 = 0 | ✅ 通过 | `check_odoo_trace.py` exit 0，50 条路由 0 命中 |
| 2 | 用户可见英文 = 0 | ⚠️ **未达标（3 处）** | `check_english.py` exit 2：`activate` ×3（`/edu/audit`） |
| 3 | 路由 × 角色矩阵 | ✅ 通过 | 500 检查点：PASS 497 / WARN 3 / PENDING 0 / FAIL 0 / ENV 0 |
| 4 | 「学费」用户可见面 = 0 | ✅ 通过 | 14 个页面实测 `学费=0`，`统筹费` 出现在应出现处 |
| 5 | 截图与首页高度（M3） | ✅ 通过 | 69 张截图；桌面 **1366**（目标 ≤1800）/ 375 **1449**（≤2600） |
| 6 | 零功能丢失 | ✅ 通过 | L1 43 PASS / L2 缺失 0 / L0 类契约 0 |
| 7 | 反面验证（越权 / 无档案 / 未选课） | ✅ 通过 | 越权 7/7 303；无档案 3/3 无他人数据；未选课 2/2 303 |
| + | 数据驱动的品牌泄漏（t9 固定项） | ✅ 通过 | `data_driven_brand_leak.py` exit 0，5 页 0 泄漏、leftover=0 |

**唯一未达标项**：第 2 项 `activate` ×3 —— 复现命令、最小复现数据、根因与一行修法见 §2。
> ✅ **已于 2026-09-12 14:5x 由 t28 修复并经 verifier 复跑确认闭合**（见 §12）。

---

## 1. Odoo / 基座品牌痕迹 = 0

```bash
python3 scripts/check_odoo_trace.py     # exit 0
```
实际输出（尾部）：
```
  教务  /downloads/manage   REDIR 303 -> /downloads?mode=manage&status=all
=== 后台（webclient，只扫文本与外链） ===
  管理员后台  /web  200 OK
PASS：Odoo / 基座品牌痕迹 0 命中（公开站 23 + 4 角色 26 + 后台 1 = 50 条静态路由，另含动态发现）
```
**结论**：通过。补充：本轮我还独立确认了**文本型**同族泄漏（`OpenEducat Bot`）已在 `/downloads`、`/edu/audit` 清零（见 §8）。

## 2. 用户可见英文 = 0 —— **未达标（3 处）**

```bash
python3 scripts/check_english.py --selftest   # exit 0（24 项断言）
python3 scripts/check_english.py              # exit 2 —— must-fix 3
```
实际输出（汇总）：
```
guest       must-fix 0    白名单 60   数据 26   主题 38
student     must-fix 0    白名单 224  数据 129  主题 122
faculty     must-fix 0    白名单 277  数据 138  主题 150
parent      must-fix 0    白名单 215  数据 71   主题 116
backoffice  must-fix 3    白名单 270  数据 138  主题 146
TOTAL must-fix = 3 条
-- must-fix 清单 --
  x3    activate    例: backoffice /edu/audit [text]  来源: views/downloads_portal.xml:411、controllers/downloads.py:860
```

**最小复现（渲染上下文取证，不是看源码行号猜）**：
```bash
python3 - <<'EOF'
import requests, re
s = requests.Session(); s.trust_env = False
s.post('http://localhost:8069/web/session/authenticate', json={'jsonrpc':'2.0','params':{'db':'edu19','login':'backoffice@local','password':'demo123'}})
h = s.get('http://localhost:8069/edu/audit').text
print([re.sub(r'\s+',' ', h[max(0,m.start()-90):m.end()+30]) for m in list(re.finditer('activate', h))[:1]])
EOF
# 实测输出： ... <td>教务专员</td> <td><span class="badge text-bg-secondary">activate</span></td> ...
```
**根因**（可直接改）：`custom_addons/edu_portal/controllers/downloads.py:883-886` 写审计日志时的中文映射字典
`{'delete': '资料批量删除', 'deactivate': '资料批量停用', 'restore': …, 'move': …, 'visibility': …}`
**缺 `'activate'` 键** → `.get(action, action)` 回落到原始动作码 `activate` → `/edu/audit` 的「动作」列原样渲染。
- 最小修法：字典补 `'activate': '资料批量启用'`（或把兜底从 `action` 改成 `'资料批量操作'`）。
- 影响面：3 条历史审计行 + 之后每次「批量启用」。
- 归属：`custom_addons/` 不在本任务范围，**未修**，交 owner（下载中心/审计线）。

## 3. 路由 × 角色矩阵

```bash
python3 tests/smoke/ux_v3_route_matrix.py   # exit 0
```
```
检查点 500：PASS 497 / WARN 3 / PENDING 0 / FAIL(真红) 0 / ENV(环境) 0
-- WARN 明细 --
  /my/checkin/board  [fac] / [bo] / [admin]  404 路由缺失
```
**结论**：通过。PENDING 已归零（`/login`、`/apps`、`/my/apps`、`/my/study` 全部可达）。
唯一 WARN 是 `/my/checkin/board` 对教师/教务/管理员 404 —— 队长已按代码实证定性为 **v2-B6 看板的既有缺陷**
（`controllers/welfare.py:172-203` 渲染 `edu_portal.edu_welfare_board`，该模板全仓零定义），非 v3 引入。

## 4. 「学费」用户可见面 = 0

```bash
# 逐页渲染计数（登录态，allow_redirects=False）
```
| 身份 | 页面 | 学费 | 统筹费 |
|---|---|---|---|
| student | /、/about、/courses-offered、/apply、/my/home、/my/study | 0 | 0 |
| student | /programs | **0** | 7 |
| student | /admissions | **0** | 4 |
| student | /my/fees | **0** | 2 |
| parent | /、/programs、/my/fees | **0** | 0 / 7 / 1 |
| backoffice | /ledger、/my/fees | **0** | 2 / 1 |

**结论**：通过（14 个页面 `学费=0`；`统筹费` 出现在招生/费用/台账等应出现处）。

## 5. 截图与首页高度（M3）

```bash
python3 scripts/shoot_ux_v3.py    # exit 0
```
```
角色/页          1280    768     375
guest/（官网）   3666    3929    5594
student/home     1366    1434    1449    ← 改前 3744 / 5889
faculty/home     1313    1371    1899
parent/home      1082    1198    1013
backoffice/home  1505    1563    2187
截图目录：tests/gap/shots/ux-v3（69 张）
```
**结论**：通过。桌面 1366 ≤ 1800、375 档 1449 ≤ 2600，均为改后实测（改前同口径 3744 / 5889）。
取样有效（`SAMPLE_VALID`）；坏窗口里的 900/1024/812 已确认是 **HTTP 500 错误页高度**，禁止引用。

## 6. 零功能丢失（L1 可达 / L2 IA 覆盖 / L0 共享类契约）

```bash
python3 tests/smoke/zero_loss_reachability.py   # exit 0
```
```
L1：PASS 43 / FAIL 0 / BASELINE-404 1（共 44 条）
L2：缺失 0
L0：类契约失败 0
结论：全绿
```
**结论**：通过。35 张旧卡 + 9 张动态卡全部可达并在 `/my/apps` 出现（L2 缺失 0）；
1 条 `BASELINE-404` 是改动前就不存在的 `my/rfq`/`my/purchase`/`student/newregistration/info` 之一，非本轮回归。

## 7. 反面验证（越权 / 无档案 / 未选课）

```bash
# 登录态逐条 GET，allow_redirects=False
```
**B1 越权**（学生访问教务/管理路由，期望 303/403，不得 200）：
```
stu /ledger                       303 /my/home
stu /ledger/new                   303 /my/home
stu /edu/audit                    303 /my/home
stu /edu/import/students          303 /my/home
stu /registrar/subject/approvals  303 /my/home
stu /leave/approvals              303 /my/home
stu /downloads?mode=manage        200 —— 已确认**无管理界面**（批量删除=0、批量停用=0、新建文件夹=0、管理模式=0；
                                  对照 backoffice 同 URL：新建文件夹=1、上传=4、管理模式=2）→ 参数对非教务被忽略，只渲染普通态
```
**B2 无档案**（家长无 `op.student`，访问学生页不得出现他人数据）：
```
par /student/profile  200  含「王小明」= False
par /my/study         200  含「王小明」= False
par /grade-book       200  含「王小明」= False
```
**B3 未选课**：
```
stu /my/courses/9999                 303 /my/courses
stu /subject/material/detail/9999    303 /subject/details
```
**结论**：通过。三条路径都没有出现"渲染他人数据"或"200 放行管理功能"的情况。

## 8. 数据驱动的品牌泄漏（t9 固定检查项）

```bash
python3 tests/smoke/data_driven_brand_leak.py   # exit 0
```
```
技术账号（id=1）创建的数据：edu_download_file=0、edu_audit_log=6
  student     /downloads               200  品牌字样=0  「系统」出现=0  OK
  student     /downloads/mine          200  品牌字样=0  「系统」出现=0  OK
  faculty     /downloads               200  品牌字样=0  「系统」出现=1  OK
  backoffice  /downloads?mode=manage   200  品牌字样=0  「系统」出现=1  OK
  backoffice  /edu/audit               200  品牌字样=0  「系统」出现=2  OK
未造样本（复用库内既有技术账号数据）；leftover=0
```
**结论**：通过。构造样本路径已自测（`created id=44 → deleted=1 leftover=0`，psql 复核 0 行）。

---

## 9. 证据等级与限制（不夸大）

1. **本文所有数字均为 verifier 本轮独立执行**；引用他方证据仅两处并已标注：
   - 两次失败升级的逐字文本（study-eng 提供，原始 `/tmp/edu19_upgrade.log` 已被覆盖，**单一来源**）；
   - `-u edu_apply` EXIT=0 已于 13:58 由 verifier **独立重跑**确认，不再是引用。
2. **生产未验证**：未对生产库做任何探测；交付报告中的「生产是否受影响」保持"未确认"。
3. **环境 vs 真回归的判读**：本轮取样全部在 `SAMPLE_VALID` 窗口内（前后比对 `docker inspect StartedAt` 一致）；
   失败特征单列 ENV、不计 FAIL（`UX_V3_GATE.md` §0）。
4. **门禁全绿 ≠ 特定数据形态下正确**：`/downloads` 的 `OpenEducat Bot` 与 `/edu/audit` 的 `activate`
   都属"随数据出现"的文本，必须靠 §8 的构造/复用样本 + 渲染上下文取证，而不是"我跑的时候是绿的"。
5. **边界说明**：本轮按队长同批指令修改了 `scripts/check_english.py`（补纯文本后缀白名单 + 收紧来源归属启发式）
   与 `tests/smoke/UX_V3_GATE.md`；前者虽在 t9 任务的 outOfScope 列表中，但属 t16 门禁收尾的延续且由队长直接指派，
   在此显式声明，避免与"验证者不该改被测物"的直觉冲突。
---

## 10. 补记（2026-09-12 14:0x，t22 交付 check_odoo_trace v3.2 后的扩展覆盖复核）

**触发**：brand-eng 交付 `scripts/check_odoo_trace.py` v3.2（新增 `--selftest` / `--list-routes` / 动态发现），
路由清单从 23 扩到 **50**（公开站 23 + 学生 10 + 教师 5 + 家长 3 + 教务 8 + 后台 1），
并新增对 ID/token 类路由（`/my/study/<id>`、`/my/study/session/<id>/join`、`/my/courses/lesson/<id>`、`/my/calendar/ics/<token>`）的跟进。

**verifier 独立复核（不是转述）**：
```bash
python3 scripts/check_odoo_trace.py --selftest   # exit 0，10/10 PASS（含动态发现正则 4/4；不依赖站点状态）
python3 scripts/check_odoo_trace.py --list-routes # 覆盖 50 条
python3 scripts/check_odoo_trace.py              # exit 0：PASS 0 命中（50 条静态路由 + 动态发现）
```

**扩展覆盖期间的中间发现（已闭合）**：brand-eng 用新清单首次扫描时命中
`教师 /my/study/35` 的可见文案泄漏技术说明（来源 `edu_portal/views/study.xml`，t6 领地）。
verifier 复核时该文案**已被修**（文件 mtime 13:41:39）：
```
<p class="ux3-hint">粘贴会议链接后，学生即可在课节卡片上「一键入会」；留空保存可撤销已设置的链接。</p>
```
且：
- 登录教师抓 `/my/study/35` → **可见文本含 `odoo` = 0**（raw HTML 里的 `window.odoo`/`__odooAssetError` 属 JS 管线，不在可见面）；
- 全量 `check_odoo_trace.py` → **0 命中 / exit 0**。

→ **结论（v3.2 文本口径）：第 1 项（Odoo/基座品牌痕迹 = 0）在当时口径下成立**（13:5x 实测 50 路由 0 命中）；
> ⚠️ **口径/时间限定（2026-09-12 15:3x 补）**：t26 起口径扩至**属性值**后，本轮出现 **23 处** core tooltip 命中
> （`title="转到您的Odoo应用程序"`，归 t29）—— 详见 **§14**。**"0 命中"是对的那个口径下的 0，不是"现在仍是 0"。**
这条中间命中按「新增覆盖后发现、归 t6、已修」记入门禁文档，**不计为脚本 FAIL**（脚本 selftest 全绿、其余 50 条全 OK，脚本是如实报出）。

**建议纳入 t9 稳定检查项**：`check_odoo_trace.py --selftest`（离线、不依赖站点状态）与 `check_english.py --selftest` 一并作为"工具自身正确性"的前置断言。

**状态更新（14:2x）**：§2 的未达标项已建 **t28**（队长派给 study-eng，inScope `controllers/downloads.py`），
任务含「补映射键 + 全量自查其它可能回落的动作码 + 未知动作要有兜底（不原样回显英文）」。
本报告在 t28 完成后由 verifier **复跑确认**（口径：`check_english` exit 0 且 `/edu/audit` 渲染英文动作码计数 = 0）。

> ✅ **t28 已完成并复跑通过（2026-09-12 14:5x）**：`/edu/audit` 渲染英文动作码 = **0**、
> 库内 `action='activate'` 行数 = **0**、`check_english` → **exit 0（五组角色 must-fix 全 0）**。
> 附录见 §12。
>
> ⚠️ t28 的一个验收陷阱（当时提前写明，现已被正确规避）：
> 只在**写入路径**补键，只能让**新记录**正常，**3 条历史行仍存库为 `activate`**，
> 页面照旧渲染英文。若验收写的是「页面英文动作码计数 = 0（含 3 条历史行）」，
> 就必须**同时**满足其一：① 清洗历史数据；② 在**展示层**做兜底映射。
> 复跑时我会按"渲染结果"判定，不看代码改没改。
---

## 11. 概念沉淀：门禁的两种粒度 —— 页面抽样 vs 数据不变量（根因判定）

本轮"假绿/假红"家族（队长概括：挂载失步的假 0、`-i` 的假成功、无锁窗口的假失败、随数据漂移的假绿）
在本任务里补上最后一块：**页面级扫描天生是抽样**。

| 粒度 | 代表门禁 | 能抓什么 | 抓不到什么 |
|---|---|---|---|
| **页面抽样** | `check_english` / `check_odoo_trace` 的路由扫描、本报告 §8 | 当时渲染出来的文本泄漏 | **当时数据没落在该页**的泄漏（换一天/换一条数据就冒出来） |
| **数据不变量（根因判定）** | t26-B 拟新增：查技术账号显示名是否含品牌 token | 泄漏的**根因数据**，与"当时渲染到哪页"无关 | 非根因类问题（新页面漏套过滤等），仍需页面抽样兜底 |

**实证**：`res_partner(2, base.partner_root).name = 'OpenEducat Bot'`（`res_users(1) __system__`）——
只要这条数据在，任何渲染 `create_uid`/`write_uid`/`user_id` 显示的**新页面、新列、chatter、导出**都可能再漏一次；
而 `_uploader_label()` / `_audit_user_label()` 是**逐页防护**（防御纵深，必要但不充分）。

**制度化建议**（已转队长，落 t26）：
1. 数据侧治根（`edu_brand` 用 `<function>` 每次 `-u` 重放改名，非手工改库）；
2. 门禁侧加数据不变量判定 —— **范围必须限定技术账号**（`uid=1` / login 命中 `__system__|__oe__|OdooBot|public`），
   不得遍历全部 `res.partner.name`（否则学员/机构名含 `odoo`/`bot` 会误报，而**门禁误报会训练大家忽略它**）；
3. selftest 增加**反向样本**（含 token 但非技术账号 → 不 FAIL）。

> 一条通用检验：**凡"结论依赖当时数据落在哪一页/哪一行"的门禁，都要配一条根因判定**；
> 否则它只是在报告"我这次看到的是干净的"，而不是"系统是干净的"。
---

## 12. 收口确认：t9 唯一未达标项已闭合（2026-09-12 14:5x）

**t28**（study-eng，inScope `custom_addons/edu_portal/controllers/downloads.py`）修复了 §2 的 `activate` 泄漏。
verifier 复跑（**判渲染结果，不看代码改没改**）：

```bash
python3 scripts/check_english.py     # exit 0
```
```
guest       must-fix 0    白名单 60   数据 26   主题 38
student     must-fix 0    白名单 224  数据 129  主题 122
faculty     must-fix 0    白名单 277  数据 138  主题 150
parent      must-fix 0    白名单 215  数据 71   主题 116
backoffice  must-fix 0    白名单 270  数据 138  主题 146
TOTAL must-fix = 0 条
```
渲染/数据双侧取证：
```
/edu/audit 英文动作码 activate 计数 = 0      （登录 backoffice 实测）
select count(*) from edu_audit_log where action='activate'  →  0
```
**结论**：t9 的七项验证现在**全部通过**；M10（英文残留 = 0）可从「508 → 0（四组角色）+3」更新为
**「must-fix 508 → 0（五组角色，含教务审计页）」**。此前 §2 的未达标记录按纪律保留，不删除。
---

## 13. 独立复核：t23 布告人群过滤（越权搜索）—— 通过（2026-09-12 15:0x）

**背景**：t23 修「`/my/search` 的布告分组缺人群过滤 —— 学生能搜到教师定向公告的标题与直链」。
flow-eng 已完成；**verifier 不复用其自述**，用**构造样本 + 正反对照 + 清场**独立复核。

夹具（odoo shell 直建，`【冒烟】` 前缀）：教师定向公告 id=67（audience=faculty）、全体公告 id=68（audience=all）。

```
=== 学生：/my/search?q=MARK ===
  含教师定向标题串: False | 含全体标题串: True      ← 反例被滤掉、正例仍在（对照组有效）
=== 学生：公告板 /my/notice_board/notice ===
  含教师定向标题串: False | 含全体标题串: True
=== 学生：直链 /my/notice/67（教师定向）===
  status=303  loc=/my/notice_board/notice  正文含标题=False   ← 直链同样不泄漏
=== 教师：/my/search?q=MARK ===
  含教师定向标题串: True  | 含全体标题串: True          ← 目标人群可达，未过度过滤
清场： CLEANED=2 LEFTOVER=0
```

**结论**：通过。三个判据同时成立才有意义：① 反例（教师定向）对学生**不可见**（搜索 + 公告板 + 直链三条路径）；
② 正例（全体公告）对学生**仍然可见**（排除「整体搜不到任何东西」的假通过）；
③ 目标人群（教师）**仍可见**（排除「过滤过度」）。

> **可复用判据（2026-09-12，flow-eng 与我互相印证后固化）**：**「列表页不显示」≠「拿不到」** ——
> 同一条受控内容必须在**三条路**上各自判一次：① 搜索/列表页；② **详情直链**（并断言 303/404 且正文不含标题串）；
> ③ **API / 导出**（CSV/PDF/接口）。只测第①条就宣布"隔离成立"，等于用更弱但更容易通过的判据替代真正要证明的东西。
> 另：判据要**成对**（反例不可见 + 正例仍可见 + 目标人群仍可见），否则"什么都搜不到"也能伪造成通过。

**③（API/导出）已于 2026-09-12 补测并复核（公告线）**：导出面 = `/my/notice_banner`（JSON）。
- flow-eng 14:36 实测：student n=1 / faculty n=2；
- **verifier 独立复核（构造样本）**：造两条 `banner_enabled` 公告（教师定向 + 全体）→ student `banners=1`（仅全体）、faculty `banners=2`（两条）→ **人群过滤在 JSON 面同样生效**；清场 `CLEANED=2 LEFTOVER=0`；
- 载荷字段为 `id/badge/text/cta/url`（不是 `title/name`）—— 我第一次复核按 `title` 取值得到"两边都是 0"的假象，**又一次"判据写错会制造假红/假绿"**（与 §18 的 `bool(env['edu.grade.history'])` 同族）；
- 复核后 DB 中 `banner_enabled=true` 公告为 0 条（默认空态 `{"banners": []}`），解释了"随手一测看不到数据"。

**新判据（采纳 flow-eng 的表述）**：**「没测到」与「不存在」必须分开写** —— 接口/导出路径先核查是否存在（路由清单 + 代码搜索 CSV/PDF/JSON 路由）：存在则按三条路同判；不存在则写明「经核查无导出路径」**并给出核查方式**。

> 方法学备注：flow-eng 自报其早期探针出现过一次假阳性（`name=True` 实为「页面回显了查询串」），
> 本次复核因此**不比对页面上是否出现查询串**，而是比对**公告标题串**（`【冒烟】…教师定向`），
> 且直链路径单独判定 —— 这正是「结论不能只看页面一句话」的实例。
---

## 14. t26 落地后的复核 + 一处**假绿被推翻**（2026-09-12 15:2x）

### 14.1 t26-A（数据侧治根）：通过
```
select u.id, u.login, p.name from res_users u join res_partner p on p.id = u.partner_id where u.id = 1
  1 | __system__ | 系统            ← 原值 OpenEducat Bot
[数据不变量] ok  uid=1  login=__system__  name=系统   →  违规 0 个
```

### 14.2 t26-C（补属性提取）：**它立刻推翻了 M1 的「0 命中」**
新门禁跑出 **FAIL：Odoo / 基座品牌痕迹命中 23 处**，全部同一类、同一来源：

```
教师  /my/home  200 HIT x1
     - attr-odoo-value    转到您的Odoo应用程序
（/assignment/manage、/my/calendar、/my/apps、/my/study、教务各页 … 共 23 处）
```

- **来源**：Odoo 自带 `website/views/website_templates.xml:295`
  `<a href="#" title="Go to your Odoo Apps" class="o_frontend_to_backend_apps_btn …"/>`
  → 官方 zh_CN 译文渲染成「转到您的Odoo应用程序」，属**用户可见**（鼠标悬停的 tooltip）。
- **此前为什么两个门禁都放过了它**（这条最有价值）：
  1. `check_odoo_trace`（v3.2 及以前）**只扫文本节点**（`TEXT_RE = >([^<>]{2,200})<`），**完全不扫属性**；
  2. `check_english` 虽然扫 `title`，但其过滤器**含 CJK 即跳过**（我文档里写过这条盲区）——
     实测 `classify('转到您的Odoo应用程序') → None`。
  → 两个门禁的盲区**恰好互补覆盖**了这个串，于是「0 命中」是**抽样口径下的假绿**，
     直到 t26 补上属性提取才被照出来。
- **与 study-eng 的「正交性」提醒一致**：`check_english` 覆盖 4 类属性 ≠ `check_odoo_trace` 覆盖属性；
  两个工具口径独立，不能互相顶替。

### 14.3 处置建议（需派任务）
1. **最小改法（i18n）**：在 `edu_zh` 的 PO 里覆盖 `msgid "Go to your Odoo Apps"` → 「转到您的应用」，
   不动上游、不动视图，一次覆盖所有内部用户的 tooltip；
2. **或（t4/edu_brand）**：该元素属于 `o_frontend_to_backend_buttons`（「门户→后台」切换器），
   与 A1「教师不再进后台」目标同源，可用视图继承对非管理员隐藏或改 title；
3. **门禁侧**：`check_english` 的「含 CJK 即跳过」策略需要一个例外 —— 至少对**属性值**里的
   `odoo|openeducat` 品牌 token 单独判一条（否则同类混排串永远抓不到）。

> 结论：**M1 在 t26 之前应写「0 命中（文本节点口径）」；补属性口径后当前为 23 处待修**。
> 这条不是回归，而是**门禁升级把已存在的泄漏照出来了** —— 恰是 t26 的价值证明。
---

## 15. 第三方独立复跑证据（flow-eng 执行，2026-09-12 15:3x）

> 执行者：flow-eng（**非发现者、非实现者**）；只读，未写任何文件；每次跑前做三步探活（无锁 / web Up≈2min 无重启 / 带 cookie 探活 302 连续三次）。

| 命令 | 结果 | 尾部输出（其原始回报） |
|---|---|---|
| `python3 scripts/check_odoo_trace.py --selftest` | **EXIT=0** | `SELFTEST PASS：13 个样本判定全部符合预期，v3 路由已纳入清单，动态发现可用`（含数据不变量 2 条反向样本） |
| `python3 tests/smoke/ux_v3_route_matrix.py --role stu` | **EXIT=0** | `检查点 100：PASS 100 / WARN 0 / PENDING 0 / FAIL 0 / ENV 0` |
| `python3 scripts/check_english.py` | **EXIT=0** | `TOTAL must-fix = 0 条`；并独立复现 `/edu/audit` 渲染上下文：`activate_count = 0` |

**对第 3 条的诚实说明（值得记录的实践）**：其首次运行在 14:2x 拿到 `EXIT=1` 且「合计 0 条」——
那是**容器重启窗口里的空扫描**，既不是真红也不是真绿，**被其主动丢弃**，未当证据使用。
→ **判读口径**：`check_english` 的「0 条」只有在**登录成功且路由数正常**时才代表绿；
空扫描应据「合并 0 条 + exit 1」识别并重跑。

**共同确认**：`activate` 那 3 处**三方均不可复现**（verifier 14:5x、flow-eng 15:3x 各自实测 `activate_count = 0`），
与 t28 的修复一致 —— t9 §2 的未达标项已闭合。

> ⚠️ 与 §14 的区分（避免误读）：本条表格里的 `check_odoo_trace` 只跑了 `--selftest`（证明**工具本身**没坏）；
> **全量扫描**当前会报 `23 处` 属性级命中（见 §14）——两者不矛盾，是不同口径。
---

## 16. t37 交付：check_english 新增 `brand` 桶（中英混排里的品牌痕迹）—— 如实报数

**动因**：§14.2 的双盲区。`check_english` 的"含 CJK 即跳过"让「转到您的Odoo应用程序」这类
中英混排值整体漏掉；t37 为它新增独立分类 **`brand`**（与 `must-fix` 并列，**同样判失败**）。

**判据与自证**（`--selftest` 26 项全 PASS）：
- `转到您的Odoo应用程序` → **brand**（必须命中）；
- `纯中文文案不该命中` → **不命中**（纯中文不报，避免误伤正常中文文案）；
- `Odoo`（纯英文）仍按 `must-fix` 处理（保持既有语义不变）。

**全站实跑（2026-09-12 15:4x，稳定窗口；`EN_EXIT=2`）**：
```
guest       must-fix 0    brand 0
student     must-fix 0    brand 0
faculty     must-fix 0    brand 75
parent      must-fix 0    brand 0
backoffice  must-fix 0    brand 73
TOTAL must-fix = 0 条 / brand = 148 条
-- brand 清单 --
  x148  转到您的Odoo应用程序    例: faculty / [attr]   来源: （未在 custom_addons 找到 —— Odoo 自带 web/website 文案）
```

**口径说明（避免两个数字看起来互相矛盾）**：
`check_odoo_trace` 报 **23 处** = "命中该 tooltip 的**路由数**"；
`check_english` 报 **148 处** = "该串在四角色 × 全部扫描页里的**出现次数**"。
**底层是同一个问题、同一条文案**（Odoo 自带 `Go to your Odoo Apps` 的官方 zh_CN 译文），
修复只需一次（t36 的 PO 覆盖 或 t29 的视图隐藏）。

> 交付纪律（队长要求）：**如实报红比报绿有价值** —— 本次 must-fix = 0 与 brand = 148 同时报出，
> 不因"看起来不干净"而把它挪进登记项。
---

## 17. t9 全绿的口径边界 + F1「审计完整性」独立复核（2026-09-12 16:0x）

### 17.1 先划清边界：t9 全绿 ≠ 审计完整性通过
t9 的七项测的是**可观测面**（路由可达、可见英文/品牌、首页高度、零功能丢失、越权/空态）。
**审计完整性（"每一次改分是否留痕"）不在任何路由/文案门禁的覆盖内** —— 它需要**行为级**验证。
study-eng 在 t13 评审中报的 F1 正是这一类：

> `OpExamAttendees.write()`（`exam_session_ext.py`）会拦截 marks 变更并**通知学生**，
> 但**不写 `edu.grade.history`** → **后台 webclient 直接改分会通知学生却不留痕**。

### 17.2 t34 修复后的行为级独立验证（verifier 执行，非读代码推断）
方法：经 `odoo shell` 以**模型边界**（等价后台 webclient 直改，不经门户路径）改一条成绩，观察留痕表，再还原并清场。

```
ATT=11 OLD=92 MAXH=0
HIST id=11 source=backend old=92 new=93 note=后台/模型边界直写     ← 后台路径已留痕（t34）
AFTER_RESTORE rows=2 marks=92                                    ← 还原值也各留一条
CLEANED=2 LEFTOVER=0 MARKS=92                                    ← 测试留痕已清，成绩原值不变
```

**结论**：F1 的审计缺口**已由 t34 修复且行为级验证通过**：
- 后台/模型边界改分 → 生成 `edu.grade.history`，`source='backend'`（t34 用 `selection_add` 扩展取值）；
- 门户三条路径（页面保存 / CSV 导入 / 上期复制）**不重复记**（`_via_managed_portal_path()` 调用栈判定）；
- 我的测试留痕已清零（`LEFTOVER=0`），被测成绩值未被改变。

### 17.3 给交付报告的两条口径
1. **"门禁全绿"必须写在它的口径里**：本轮 t9 全绿 = **可观测面**全绿；不要外推成"业务正确性/审计完整性全绿"。
2. **claim 与证据要同级**：F1 的教训是"改分唯一入口、全部留痕"是**claim**，
   而 `write()` 只做了通知 —— **行为级验证（写一次、看留痕表）才能证伪/证实**，
   读代码、读路由、看页面都测不出来。
---

## 18. 假绿家族的第六个变体：「服务在跑 ≠ 系统可维护」（2026-09-12 深夜 P0）

**事件**：`custom_addons/**/models/__init__.py` 导入顺序错误 →
`TypeError: Model edu.grade.history does not exist in registry`。
**站点照常服务**（HTTP 302/200 全正常），**只有 `-u` / `odoo shell` 全炸**。
由 study-eng 抢修（把顺序约束写进文件注释）。

**对门禁的直接影响（这条最该记住）**：
- **HTTP 类门禁全绿**：路由矩阵、check_english、截图、品牌泄漏 —— 它们不碰注册表装载路径；
- **shell 类工具全红/不可用**：`audit_completeness_smoke.py`、数据不变量查询、各类 fix/seed 脚本、
  以及**交付前必跑的 `-u` 升级**。
→ 与 §17 的「t9 全绿 = 可观测面全绿」同族：**绿的是被观测到的那一面，不是系统整体**。

**verifier 独立复核（2026-09-12 修复后，odoo shell 直查）**：
```
MODELS=691                （注册表装载成功）
HAS_MODEL=True            （edu.grade.history 在册）
SEARCH_OK=6               （可正常查询留痕表）
source selection = [('manual','页面录入'),('import','文件导入’),('copy','上期复制'),
                    ('system','系统'),('backend','后台直改')]   ← t34 的 selection_add 生效
```
（附带一条自嘲：我第一次判定写成 `bool(env['edu.grade.history'])` → 空 recordset 天然为假，
得到"注册表坏了"的**假红**。**判据写错会制造假红，和假绿一样有害** —— 这也是本报告反复出现的主旋律。）

### 18.2 「断言自身有缺陷」家族（与假绿并列，同样有害）

| 实例 | 缺陷形态 | 后果 | 出处 |
|---|---|---|---|
| 取值字段名错 | 载荷是 `id/badge/text/cta/url`，按 `title/name` 取值 | 得到"两边都是 0"的**假绿** | §13（公告线第③条复核） |
| 空 recordset 真值 | `bool(env["edu.grade.history"])` 天然为假 | 得到"注册表坏了"的**假红** | §18 |
| 载体未先证合法 | 夹具/样本本身未生效就当证据 | 假绿或假红（study-eng 自降级 t43 一条证据） | 交叉印证（study-eng） |
| 查询串回显算命中 | 把"页面回显了查询串"当成"搜到了受控对象" | 假红（flow-eng 早期探针） | §13 方法学备注 |

**共性判据**：**断言必须先自证忠实**（字段名对、空态≠缺陷、夹具确实生效、判据能被反例证伪），再拿它去量被测对象 —— 否则测出来的是断言自己的毛病。
**给门禁的处置建议**：离线自证族（`check_odoo_trace --selftest` / `check_english --selftest` / 接缝测试）
之外，再加**一条注册表可装载性断言**（一条 5 秒的 `odoo shell` 探针，或直接复用 `safe_upgrade.sh` 的装载前置），
让"可维护性被破坏"以明确的类别暴露，而不是让 shell 类工具报一堆看不懂的错误。

### 18.1 采纳 study-eng 的两条操作性判据（并入交付口径）
1. **任何"全绿"陈述必须带覆盖对象与未覆盖项**（哪些路由/角色/位置/属性），把覆盖率变成**可审计声明**——
   `check_english` 已落成 `--coverage`；其它门禁建议照做（`check_odoo_trace` 已有 `--list-routes` 与"动态模式 N 类/实际跟随 M 条"）。
2. **claim 与证据同级**：**若一个 claim 无法被一次行为级测试证实/证伪，就把它降级为"设计意图"表述**，
   不要在报告里以断言形式出现（t13-F1 能被闭环，正因为它当时就是可行为化验证的 claim）。
---

## 19. t26（A 治根 + B 数据不变量）独立复核（2026-09-12 深夜）

**A 显示名治根** —— verifier 直查数据库（非引用实现者自述）：
```
uid=1  __system__  active=f  →  partner.name = 系统      ← 原值 OpenEducat Bot（改名生效，login/active 未变）
```
→ 与 brand-eng 的实现说明一致（`<function>` 每次 `-u` 重放；base.partner_root 两个 root 记录都是 noupdate=t）。
附带收益确认：外发邮件/通知的作者名不再出现基座品牌。

**B 数据不变量** —— 门禁自述与实跑一致：
```
[数据不变量] ok  uid=1  login=__system__  name=系统  →  违规 0 个
check_odoo_trace 全量 → PASS：0 命中（公开站 24 + 4 角色 27 + 后台 1 = 52 条静态路由 + 动态发现）
[邮件面] 覆盖 4/4 支模板，未覆盖 0 支            ← 第四维（页面/属性/邮件/数据不变量）
--selftest → 13/13 PASS（含两条反向样本：非技术账号名里含 token 不 FAIL）
```

**发现一条口径差异（latent，建议对齐）**：
```
scripts/check_odoo_trace.py:133  TECH_LOGINS = ('__system__', 'system', 'odoo', 'openerp')
controllers/contacts.py:27      _TECH_LOGINS = {'__system__', '__oe__', 'OdooBot', 'public'}   ← 仓内权威集合
```
- 影响：若将来库里出现 `__oe__` / `OdooBot` / `public` 创建的记录，逐页过滤器会显示「系统」，
  但**数据不变量门禁不把它们算作技术账号** → 两侧口径不一致；
- **当前是 latent**：本机只存在 `__system__`(1) 与 `public`(3)；`__oe__`/`OdooBot` 不存在，
  且 `public` 的显示名 "Public user" 不含 `openeducat|odoo|bot` → 即便纳入也不会误报；
- 建议：以 `contacts.py` 为准对齐（多覆盖 `__oe__`/`OdooBot`/`public`）+ selftest 加一条断言。

**（已处置 · 2026-09-12 t54）** 显示名 `Public user` → **公众用户**（login `public` 未动 → `_TECH_LOGINS` 按 login 的匹配与门禁数据不变量均不受影响）；verifier 复核 DB：`3|public|公众用户` ✓。

**（原始观察留档，不夸大）**：`public` 账号显示名曾是英文 `Public user`（uid=3，active=f）。
门户侧由 `_TECH_LOGINS` 映射为「系统」，**后端 webclient 的"创建人"列仍会显示英文**；
是否处理（改名/白名单）属产品口径，交队长与用户决定，verifier 只登记不擅改。

---

## 20. 两条新增判据（来自 flow-eng / study-eng 的交叉印证，2026-09-12 收口）

### 20.1 三层检测分工：「`-u` EXIT=0」与「页面能开」是两个独立命题

| 类 | 故障形态 | 谁能抓到 | 证据 |
|---|---|---|---|
| 类 1 | XML 语法错（如 `<script>` 里 JS 裸 `<`） | 任何解析器 / 静态检查器；`-u` 装载期 | 13:11 的 `roles.xml:631` 事故 |
| 类 2 | 继承视图 xpath 0 命中 | `-u` 装载期 + 静态检查器 | 13:13 的 `edu_registrar_subject_approvals_bulk` 事故 |
| 类 3 | **渲染期 QWeb 指令错**（如 `t-elif` 前无 `t-if`） | **只有逐路由真渲染**；`-u` **不报** | flow-eng 实测：`-u` EXIT=0 而 `/registrar/subject/approvals` 直接 500（QWeb 惰性编译，arch 入库不算，首次渲染才炸） |

**推论（写进交付口径）**：**“`-u` EXIT=0”只证明类 1/类 2 过；“页面能开”要另测。**
这份逐路由矩阵（100 路由 × 5 角色）与 `check_view_xpath`（离线静态检查）是**互补而非重复**：
前者是唯一覆盖类 3 的一层，后者把类 1/类 2 提前到"升级前"。

### 20.2 误报与漏报要用不同方式证明

- **误报（把不该报的报了）** → 用**反向样本**证明：`check_english --selftest` 里的「纯中文文案不该命中」、
  `check_odoo_trace` 的两条非技术账号反向样本、接缝测试的 (e) 纯中文对照。
- **漏报（该报的没报）** → 用**新增一类载体的构造样本**证明：接缝测试的 (c)/(d)（CJK+品牌 token）、
  以及 (f)（未登记属性 `data-tooltip`，known-gap 被测试钉住）。
- 两者**不可互相替代**：词边界/白名单修复解决的是误报，属性覆盖面解决的是漏报；
  用"反向样本全绿"去论证"没有漏报"是**不同层级的证据**（本轮反复栽过的"用更弱但更容易通过的判据"）。

> 附：「互补 ≠ 并集完备」的准确措辞是**「跨着跑覆盖面更大」**，而不是"一起跑就没有属性盲区"
> —— 两个门禁合起来覆盖 `文本节点 + title/placeholder/aria-label/alt`，其它可见属性载体（`aria-description`、`data-tooltip`、`value`）两者会同时漏。

---

## 21. t41 复核 + 邮件数据面口径纠正（2026-09-12 深夜）

### 21.1 TECH_LOGINS 对齐：已落地并独立复核
```
scripts/check_odoo_trace.py:164  TECH_LOGINS = ('__system__', '__oe__', 'OdooBot', 'public')
                                 ↑ 与 controllers/contacts.py:27 的 _TECH_LOGINS 一致；
                                   第 160 行注释写明「门禁与应用侧两套集合迟早会漂移」的双向同步约束
--selftest → SELFTEST PASS：13 个扫描样本 + 7 个数据不变量样本（含正反断言）全部符合预期
```
- 数据不变量样本含 brand-eng 特别加的那条边界：`('public', 'Public user')` → 集合内**但名字无品牌 token → 不 FAIL** ✓
  （正是我 §19 提醒的"别把 Public user 变成待修项"）；
- 过程中其 selftest **抓到一个真缺陷**：集合里 `OdooBot` 是混合大小写、SQL 侧用 `lower(login)` 比较 → 首跑 FAIL；改用 `TECH_LOGINS_LC` 后通过。
  这是"反向样本/正反断言"价值的又一实例 —— **门禁自己抓到了实现里的真错**。

### 21.2 邮件数据面口径纠正（我在别处引用过的数字要按这版）
brand-eng 先前报的「mail.template 44/47 条记录」是**匹配组合数**，不是记录数。**正确口径（已写死进工具输出）**：
```
[数据面] mail.template  命中记录 15/47（其中可见文案 12 条；匹配组合 44）（待修，见样本）
[数据面] digest.digest  命中记录 0/1（其中可见文案 0 条；匹配组合 0）
[邮件面] 覆盖 4/8 支模板，未覆盖 0 支（未覆盖即计入失败，不做静默跳过）
```
→ 留档统一记 **15 命中记录 / 12 可见文案 / 44 匹配组合**。

### 21.3 一条必须写清的措辞边界（"0 命中"是哪个口径的 0）
`check_odoo_trace` 的 PASS（exit 0）指的是**四维**：页面文本 / 属性值 / 邮件投递面 / 数据不变量。
**邮件"数据面"（mail.template 的 subject/body_html，逐安装语言扫）被显式单列为「本轮待修面」，不计入四维命中**（工具第 392/567 行注释写明）。
因此当前准确陈述是（**两个计数都要给，否则会各说各话**）：
> **四维 0 命中；邮件数据面待修 4 条模板 / 15 条命中记录（12 条可见文案；44 匹配组合）** —— 由工具显式打印、不计入四维判据。
> 不得简写成"邮件面已全清/门禁全清"，也不得只报其中一个数（模板数 4 与记录数 15 是两种口径，都有意义）。

**两个计数的口径对照**（来自同一份输出）：
· **[模板正文] ⚠ 待修面 4 条** → **模板级**：命中的 mail.template 支数（4 支）；
· **[数据面] mail.template 命中记录 15/47（可见文案 12 条；匹配组合 44）** → **记录/字段/语言级**：逐安装语言扫出来的命中记录数 15、其中可见文案 12、匹配组合 44。
流量的独立性佐证（flow-eng 读数）：14:29:05 该双指针为 **EXIT=1 / 5 处 / 44-47**，14:33:11 变为 **EXIT=0 / 4 条待修** —— 中间是 t31 落地，**四维确实清了、数据面仍留待修项**，且工具从未静默跳过（两行都打印）。

> 同族纪律回顾：这正是本报告反复出现的「**全绿必须写在它的口径里**」——第四种假绿的变体是"把不计入判据的面当成已清"。


### 21.4 队长裁决（2026-09-12 深夜）：4 条收口 / 11 条登记为「已声明待修面」
- **可达的 4 支模板**（收件人必有：3 条 `auth_signup` 注册/设密码 + 1 条 `auth_totp_mail`）→ 任务 **t54**（brand-eng）：
  用 `<function model="mail.template" name="write">` 每次 `-u` 重放、**逐语言**写成自有中文（`noupdate=t` 使 PO 与普通 `<record>` 都改不动，这是唯一可行路径）。
- **其余 11 条**（account / sale / hr / event / gamification / website_slides 等**未启用应用**）→ **不立任务**，登记为**已声明待修面**（交付报告 §3.5.1）：
  **不计为通过、也不沉默**（门禁每次显式列出）；判据是**可达性**（渲染路径不可达，与 `account` 两条电子发票模板同一口径）。
  **若日后启用相应应用 → 另立任务再评估**。
- 该裁决同时确立了**第四种假绿的处置口径**：**「不计入判据的面」不得当成「已清」** —— 引用门禁结论时必须连着它自己的口径一起抄。

**后续验证安排**：t54 收口后，由 verifier 复跑、并请 flow-eng 做**第二方独立复跑**（同一口径：先三步探活 → 读数 → 同时记录**模板级 4** 与**记录级 15/12/44** 两个计数）。

**t54 收口后的复跑配方（可直接照抄执行）**：
```
# 1) 三步探活（缺一不可；失败=环境问题，不是回归）
ls "${TMPDIR:-/tmp}/edu19_upgrade.lock" 2>/dev/null && echo LOCK || echo "no lock"
docker compose ps --format '{{.Name}} {{.Status}}' | grep web-1        # Up > 30s
J="${TMPDIR:-/tmp}/cj"; rm -f "$J"; curl -s -c "$J" -b "$J" -o /dev/null -w '%{http_code}\n' \
  'http://localhost:8069/web/login?db=edu19'                          # 200/302/303

```

### 21.5 t54 收口后的复测（2026-09-12，verifier 独立执行）

读数已变，**留档以本段为准**（旧读数 15/12/44 见 §21.2，属 t54 之前）：
```
[邮件面] ok  auth_signup.set_password_email / portal_set_password_email /
             mail_template_user_signup_account_created / auth_totp_mail.mail_template_totp_invite   ← 4 条「真会发」的已治净
[模板正文] ok ×4（数据层 subject/body_html 干净、渲染成功）
[数据面] mail.template  命中记录 **11/47**（其中可见文案 **8** 条；匹配组合 **29**）（待修）
[数据面] digest.digest  命中记录 0/1
[邮件面] 候选 8 支（QWeb 4 + mail.template 4）/ 渲染成功 8 / 未覆盖 0 / 数据记录待修 0
TRACE_EXIT=0
```
→ 准确陈述：**四维 0 命中；邮件数据面仍有 11 条命中记录（可见文案 8）—— 待修面，单独计数。**
其余 11 条中 `account` 的两条（`einvoice_notification` / `invoice_subscriber`）经实测判**不可达**
（国家 US、`account_peppol` 未装、`account_move`=0、arch_db 零引用），按可达性口径**登记不修**。

**PASS 语义的进一步强化（t55 后）**：`PASS` 现在**额外蕴含「所有面都被真正验证过」** ——
若存在未验证面（例如 `odoo shell` 起不来导致邮件面没扫到），strict 默认**判失败**、汇总写 `INCOMPLETE`
（退出码 1；`--lenient` 时 3）。因此「PASS」不再可能覆盖"某个面没扫"这种情况。

### 21.6 两条新流程规矩（本轮立，已被两次事故验证）
1. **验收写结果、不写手段**：t52 的失败不是"没做出来"，而是**契约写了数据面上不可实现的 xpath**
   （`mail.template.body_html` 是数据记录，xpath 改不动）—— 把手段写进验收，就会把本该用
   `<function>` 的修复判成失败。
2. **宽松模式只能放宽退出码，不能放宽结论标签**：`--lenient` → 退出码 3，但汇总**仍写 `INCOMPLETE`**，
   **绝不给 PASS**。即"容忍未验证"不等于"宣告通过"。

**报告更新分支**（队长 2026-09-12 批准）：数据面清零 → M1/§3.4 写「数据面亦已清零」并保留两行过程计数；
仍有显式待修面 → 保持「四维 0 命中；数据面待修 N 条模板 / M 条命中记录」，**不写"全绿"**。
---

> **§21.7 的位置**：它排在 `## 22` 之后（历史插入顺序错位），请按编号查找。

## 22. 独立复跑：authz_endtoend_smoke（t43 越权冒烟）—— verifier 执行（2026-09-12 深夜）

**执行者：verifier（独立执行，非引用 study-eng 自述）**；命令：`python3 tests/smoke/authz_endtoend_smoke.py`（自带两轮）。
结果：**断言 31 条：PASS 31 / FAIL 0，AUTHZ_EXIT=0，耗时 57.3s**；两轮 DB 终态一致。

**判据表（含队长点名的两条前置/正对照，原文照录）**：
```
PASS 前置：越权方是合法教师（current_faculty 口径命中 1 条）   INTR_LOOKUP=[75]（第2轮 [76]）
PASS 正对照·属主 save 成功改分（排除功能被锁死）              after_owner=77
PASS 成绩·单条 save 越权后 DB 未变                       before=60 after=60 http=303
PASS 成绩·导入确认 越权后 DB 未变                        before=60 after=60 http=303
PASS 成绩·上期复制 越权后 DB 未变                        before=60 after=60 http=303
PASS 成绩·导出 不泄露该考试内容                           http=303 len=215 名称命中=False 数字命中=False
PASS 成绩·导入预览 不泄露该考试内容                         http=200 len=40256 名称命中=False 数字命中=False
PASS 不泄露存在性（越权 id 与不存在 id 响应不可区分）            real=(303,/grading/entry,215,False) fake=同
PASS 还原越权/正对照改动                               restored=60
PASS 批量审批·请假/申诉/选课 越权后状态未变                   before=request after=request（三条各自）
PASS 清场 leftover=0（active_test=False 复核）          LEFTOVER_EXAM=0
PASS 清场 成绩留痕 leftover=0                          HL=0
PASS 连跑两次 DB 终态一致                             leftover_exam / history_leftover 双 0
```

**两条关键判据为什么必须在内（队长裁定，照录）**：缺了它们就分不清"越权被拒"与"根本没身份被拒"——
① 前置断言证明**越权方确实是合法教师**（op.faculty.search 命中 1 条），即 current_faculty() 的真实判据；
② 正对照证明**同一操作由属主执行必然成功**（排除"功能被整体锁死"造成的假通过）。

**与 study-eng 报数的差异（如实记录，按队长口径以 verifier 为准）**：
study-eng 入库时报 **29/29**；本次我实测 **31/31**（两轮各 15 条 + "连跑两次 DB 终态一致" 1 条）。
差异**只在断言条数**（其版本之后应已新增断言），**结论一致：两轮 0 FAIL、越权写入 0 落库、清场 0 残留**。
记录此差异的意义：断言数会随版本增长，**引用他人的"N/N 全绿"必须带上执行时间与版本**，否则无法判断是不是同一版。

**我的独立结论**：31 条断言本次全部成立；越权路径（成绩单条/导入/复制 + 三类批量审批）均**未改动数据库**，
越权 id 与不存在 id 的响应**无法区分**（不泄露存在性）；夹具与成绩留痕清场归零。
### 21.7 数据面读数再更新：11/8/29 → **10/47**（口径修正，非扫描缩水）｜2026-09-12 深夜

> **位置说明（2026-09-14 t110 复核）**：本节编号属 **§21（数据面口径）**，但因历史插入顺序错位排在了 **§22 之后** —— 内容归属**按编号读，不按位置读**；**未搬动正文**（避免改写历史）。

**verifier 独立复跑**（绑定工具自证行，避免"数字追不上"）：
```
[数据面] mail.template  命中记录 10/47（其中 1 条属内部核心链接型，按 /odoo、/web 口径不计；可见文案 8 条；匹配组合 29）（待修）
[数据面] 可达命中 4 条 / 不可达登记 6 条（按本部署可达性口径，登记理由见代码 UNREACHABLE_MODULES）
③ 内部核心链接（/odoo/…、/web/…，属核心命名空间取舍） —— 本次邮件面剥离 15 处；数据面 内部链接型 1 条（mail_template_base_install_request）
REVISION=v3.6 · 指纹 0461231c · 断言 24 条        ← 自证行（t58 起每次打印）
TRACE_EXIT=0
```

**11 → 10 是记账口径修正**：base_install_request 的 odoo 仅出现在 t-attf-href="/odoo/…" **内部核心链接**里，
而门禁自己写明的口径是"内部核心命名空间链接不算品牌命中"（页面与邮件投递面早已如此）——
这次是让**数据面 headline 与它们同一套口径**。四维判定与退出码未变。

**留档纪律（本轮新增，采纳 brand-eng 建议）**：引用门禁数字时**必须连自证行一起抄**
（`REVISION · 指纹 · 断言 N 条`）——本次记的是 **v3.6 / 指纹 0461231c / 24 条**；
工具再改时一眼可判"这份读数属于哪一版"，不必重新核对数值。

> 过程留档（按时间）：15/12/44（t54 前）→ 11/8/29（t54 后，§21.5）→ **10/47 口径修正（本段，v3.6/0461231c）**。
---

## 23. 断言层独立复评：t61 教师夹具构造器（换人换方法）｜2026-09-12 深夜

**层级声明**：本节做的是**断言层** —— **换人 + 换方法**（不是"换人跑同一个脚本"）。
study-eng 做的是执行层（它自己写了 t61 并跑了 31/31）；我这里**不复用它的负例注入方式**，
改用**自己的手法**：monkeypatch 模型类 `res.partner.write`，从 vals 里**剥掉 user_id**。
探针只读、脚本在 /tmp（不污染仓库）。

### 23.1 负例：漏写 partner.user_id 时，构造器必须"以预期方式"拒绝

按队长追加的**四步前置**执行（防止"我的屏蔽没生效 → 误判构造器没拦住"）：

| 步 | 内容 | 实测 | 证据等级 |
|---|---|---|---|
| 1 | 我自己的手法造"漏写"载体（partner → users → op.faculty，全程屏蔽 partner.write 的 user_id） | 建出 partner/user/faculty 三件套 | **执行验证** |
| 2 | **先证明载体确实半合法**（我自己的通道：裸 SQL + ORM search + teacher_lookup） | `S2_PARTNER_USER_ID=None`、`S2_SQL_JOIN=[]`、`S2_SEARCH=[]`、`S2_LOOKUP=op.faculty()` → `S2_MASK_WORKED=True` | **执行验证** |
| 3 | 同一屏蔽下走构造器，断言**以预期方式**拒绝 | `S3_TYPE=HalfLegalTeacher`、`S3_IS_EXPECTED=True`、`S3_IS_ASSERTION=True`、`S3_MSG_HAS_LOOKUP_EMPTY=True` | **执行验证** |
| 4 | 若第 2 步失败则判"我的测试坏了" | 本次第 2 步通过，故第 3 步结论成立 | 纪律条款 |

第 3 步原文消息（可读、含原因与期望值，**不是** except Exception 一网打尽）：
```
make_teacher 建出的载体不合法：teacher_lookup(uid=128)=[] （期望恰好 [89]）。多半是漏写 partner.user_id。
```
断言方式是**具体类型 + 正则**：`isinstance(e, HalfLegalTeacher)` 且消息匹配 `teacher_lookup\(uid=\d+\)=\[\]`。

### 23.2 正例：join 通道 vs teacher_lookup() 口径一致（两条通道互证）
```
op_faculty 是否有 user_id 列： 0      ← flow-eng 踩过的坑（_inherits 委托字段，SQL 侧无此列）
res_partner.user_id 列：        1
通道 A（我的 SQL join）：select f.id, p.id, p.user_id from op_faculty f join res_partner p on p.id=f.partner_id where p.user_id=126
                          → [(87, 188, 126)]
通道 B（teacher_lookup）：op.faculty(87,)
通道 C（current_faculty 同域 search）：[87]
POS_CLEAN={'partners': 0, 'users': 0, 'faculties': 0}
```
→ **三条通道完全一致**（faculty 87 / partner 188 / partner.user_id 126）。

### 23.3 逐条证据等级

| 结论 | 等级 | 说明 |
|---|---|---|
| 负例：漏写 user_id 时构造器拒绝，且以预期类型/文案 | **执行验证**（我的手法 + 四步前置） | 见 23.1 |
| 正例：合法教师可被解析，SQL join 与 teacher_lookup 一致 | **执行验证** | 见 23.2 |
| `op.faculty` 无 user_id 列（委托字段） | **执行验证**（information_schema） | 0 行 |
| 构造器"绝不静默通过"这一设计意图 | **仅代码验证**（读构造器逻辑与断言位置） | 未构造"删掉断言"的变异体 |
| 越权冒烟整体（31 条） | **执行验证**（我独立跑，见 §22） | 本轮复跑 31/31 再次确认 |

### 23.4 我的独立结论（与 study-eng 一致；按队长口径以 verifier 为准）

1. **构造器守卫有效**：在"载体半合法"可被独立证实的前提下，它**以预期方式**抛错，消息可指向原因（漏写 partner.user_id）；
2. **两条通道口径一致**：`res_partner.user_id` 的 SQL join 与 `teacher_lookup()`（即 current_faculty() 的判据）给出同一结果，
   说明该口径与生产登录判据同源，不是作者的私有定义；
3. 未发现 t61 的实现缺陷；也未发现"断言被静默吞掉"—— 31 条断言重构前后**条数不降**（我本轮独立复跑同为 31/31）。
---

## 24. t81 定性：authz 冒烟的 2 条 FAIL = **并发竞争**，非回归（2026-09-12 16:03 定论）

### 24.1 失败断言名（来自 t76 审计历史 + 我的复跑）
审计历史（tests/smoke/.assertion_history.json，last_seen=2026-09-12 15:55:54）中 authz_endtoend_smoke.py 的 FAIL 记录共 **5 个名字**：
```
t75 越权·ok=0 fail=0 skip=0（越权 id 静默丢弃、不计 skip）            last=FAIL
t75 越权后 DB 未变（regB 仍 submitted，且本可观察）                  last=PASS
正对照·属主 save 成功改分（排除功能被锁死）                          last=PASS
还原越权/正对照改动                                              last=PASS
连跑两次 DB 终态一致                                             last=PASS
```
即：**后续运行已把其中 4 条打回 PASS** —— 这是"竞争"的典型形态，不是"契约被改坏"的形态（后者会稳定复现）。

### 24.2 三次读数（同一份代码，结论随窗口而变）
```
① 15:51 前后（并发）  67 条：PASS 65 / FAIL 2   ← FAIL=「清场 leftover=0」LEFTOVER_EXAM=None、「连跑两次终态一致」
② 15:54:48–15:56:24    67 条：PASS 62 / FAIL 5   ← FAIL 全为夹具读数缺失：after_owner=GONE / restored=GONE /
                                                    t75 ok/fail/skip=None（该窗口内 ps 见 2×assertion_audit.py
                                                    + aux4_batch_smoke.py + zero_loss_reachability.py + c_browser.py 在跑）
③ 16:03:30–16:04:57    67 条：**PASS 67 / FAIL 0**  ← **安静窗口**：开跑前 competing=0、无升级锁、探活 302；跑完 competing=3
   AUTHZ_EXIT=0
```
**判据**：若是在途改动（t67 作用域提取 / t77 的 enroll.py）导致的契约破坏，同一份代码应**稳定失败**；
实测是**同一份代码 3 次读数 65→62→67**，失败项全是"夹具读数 GONE/None"这类**竞争指纹**，安静窗口即全绿，
⇒ **定性：环境/竞争**（既不是"在途改动所致"，也不是"真实回归"）。

### 24.3 flow-eng 那条假设（属主正对照落在作用域外）—— **不成立**
安静窗口下「正对照·属主 save 成功改分（排除功能被锁死）」与「t75 属主正对照·批量通过 ok=1 / approved」均 PASS；
底数核对：**faculty@local(id=17) 任教班级 = [8]**，学生 5 的在读 batch 也是 **8** → 属主**在作用域内** ✓（判据要求"相交"，实测相交）。

### 24.4 报告里那条「第三方独立复跑 31/31」怎么改
**结论仍成立，但数字已过期** —— 脚本断言数由 31 增至 **67**（t75 自建【冒烟】选课单 + 属主正对照已入库，提交 9a436be）。建议改写为：

> **authz 越权冒烟：67/67（2026-09-12 16:03–16:04，安静窗口：并发进程 0、无锁、探活通过）**；
> 该冒烟使用**共享夹具**，**不得与其它冒烟并发** —— 并发窗口实测 62/67 与 65/67（失败项为夹具读数竞争，非断言语义），
> 引用时**必须带版本、时间与"是否独占"**（与 §0「读数自证头」同一纪律）。

> 本页也是一条判据的实例：**共享行上的"未变"断言是对全称的判断** —— 任何人动过它都会红。
> 团队已在提交 1cc9f93 记下「共享夹具不得并发」，并把该断言改为「state+write_date 指纹一致」。
---

## 25. t91 静态阶段：通知/提醒卡/收藏 5 条红项（环境冻结期只做静态，**活体待解冻**）

> 冻结令期间（docker daemon 500、无容器服务）**一律不跑 HTTP**；本节只给「**静态结论 + 解冻后要跑的那一步**」，
> **不给最终定性**（真缺陷 vs 脚本陈旧 需要活体读数）。

### 25.1 五条逐项

| # | 失败断言 | 静态结论（依据：文件:行） | 解冻后只需跑这一步 | 证据等级 |
|---|---|---|---|---|
| ① | p3_ledger L14a「通知 reimburse_result ≥2」 | **静态链完整无缺口**：路由 `/ledger/reimburse/set`(ledger.py:473) → `action_reimburse_approve/refuse/pay` → `_reimburse_notify`(fees.py:289/312/347) → `_notify_event(reimburse_result)`(fees.py:202 + notify_pref.py:21)。脚本按**自建单号 ref** 统计（非共享行），且 Z2 清理在 L14a **之后** | 跑一次 p3_ledger，读「相关通知=N」（期望 ≥2） | 静态=执行级读码 |
| ② | a1「3 学生首页提醒卡(请假状态已更新)」 | 该串**不是首页模板硬编码**，来自**路由键提醒机制**：batch2.py:318 (`my/time_off`, `您的请假状态已更新`) ⇒ 渲染与否取决于 **v3 首页是否仍渲染提醒卡**（与④同族） | 学生 GET `/my/home` 看该串；再查 v3 首页模板(study.xml ux3-home)是否保留提醒卡区域 | 静态=执行级读码 |
| ③ | aux2「成绩录入提醒到达」 | **静态无缺口**：文案仍在（exam_session_ext.py:89），且走**静音感知**通道 `_notify_event(grade_result,…)` | shell 触发 write 后数 `edu_message body LIKE 成绩已录入`（脚本 2a 原样） | 静态=执行级读码 |
| ④ | aux3 收藏/csrf **5 条（级联）** | **最可能是级联**：`data-csrf`/`data-fav-server` **只在旧模板**（batch2.xml:667-668 edu_dashboard_v2、844-845 edu_dashboard_teacher），v3 学生首页是 study.xml 的 ux3-home，**全仓无第三处**；辅助：失败明细「收藏保存 200」实测值是 `<!DOCTYPE html>`（csrf 失败返回 HTML 错误页） | 学生 GET `/my/home` 看有无 `data-csrf`；若无，再确认收藏入口在 v3 是否另有落点（有=脚本陈旧；无=产品缺口） | 静态=执行级读码 + 审计明细 |
| ⑤ | p5_acd「静音后成绩提醒不到达」 | **静态链自洽**：静音保存语义与测试一致（**缺席字段 ⇒ muted=True**，favorite.py:70-82）、事件键对齐（grade_result，notify_pref.py:16）、成绩通知走静音感知 `_notify_event` | shell 触发后数 `event_key=grade_result` 的消息数（期望 0） | 静态=执行级读码 |

### 25.2 假红排除（本轮既定口径）

- **非共享行**：① 用自建单号统计；③⑤ 用 shell 计数；④ 无共享行依赖。
- **但全部落在 15:5x 的高并发窗口**（t76 审计会顺序跑多个冒烟；实测彼时有 2×assertion_audit + aux4 + zero_loss 并发）⇒
  **解冻后必须在安静窗口复跑**才能定性 —— 与 t81（authz 2 条 FAIL 的定性）同一条教训：**竞争 ≠ 回归**。
- ② 的「rc=2 与 FAIL 并存」属**退出码语义**问题（判据：rc 应与 FAIL 数一致），静态可判、修法归 owner。

### 25.3 解冻后的执行顺序（照此，不重复发现）
1. 安静窗口 + 三步探活 → 2. 单独跑 5 个脚本各一次 → 3. 按 25.1 第 4 列逐条核对 →
4. 真缺陷则**汇总 1–2 个修复任务建议**（inScope + 验收）；脚本陈旧则交 owner，**本任务不改业务代码**。
---

## 26. t91 活体确认（2026-09-12 16:13–16:20）：**5 条全部不是产品缺陷**，根因分三类

取样条件：开跑前 `probe=302`、`competing=0`（安静窗口），队列顺序跑 5 个脚本；宿主负载约 12（偏高但不构成阻塞）。
另有两次定点复现（报销链路 / 提醒卡链路），全程**只读业务代码**，测试数据用后即清（`leftover=0`）。

| # | 最终结论 | 可复现证据 | 与 §25 静态的关系 |
|---|---|---|---|
| ① p3_ledger L14a「相关通知=0」 | **夹具/共享状态问题，非缺陷** | 用户 8 的偏好里 `reimburse_result=**muted=True**`（另有 subject_reg_result 同样被静音）⇒ 报销通知被**正确地**抑制。定点复现：走真实门户链路建单（`/my/reimburse/apply/save` → REB000222），教务 `/ledger/reimburse/set` 审批成功（`reimburse_state=approved, approved_amount=80.0`），而 `edu_message` 计数 0 —— 与被静音一致 | 静态判"链完整"✓ 得到证实；**根因在共享状态，不在链** |
| ② a1「学生首页提醒卡=False」 | **脚本陈旧（v3 页面迁移）+ 该脚本 rc 语义 bug** | 学生 `/my/home`（v3 `ux3-home`）**无**该文案；把学生请假改为 approved 后 **`/my/apps` 出现「您的请假状态已更新」**（另一页同一数据源）⇒ 卡片迁到 /my/apps，产品能力在。另：`FAIL=1` 时脚本 `rc=2`（语义不一致） | 静态"取决于 v3 首页是否仍渲染"→ 活体给出答案：**迁到 /my/apps** |
| ③ aux2「成绩录入提醒到达」 | **脚本判据陈旧（绝对基线）** | 按脚本原样复现：`WRITE_OK`、`MARKS_MSG=**364**`（历史累计）；脚本断言字符串是 `MARKS_MSG 1` ⇒ 永不成立。通知**确实到达** | 静态"链无缺口"✓ 得到证实 |
| ④ aux3 收藏/csrf 5 条 | **脚本陈旧（v3 页面迁移）** | 学生 `/my/home`：`data-csrf=False`；**`/my/apps`：`data-csrf=True, data-fav-server=True`** ⇒ 收藏 SSR 容器随 35 瓦片一起迁到 /my/apps | 静态"只在旧模板"→ 活体确认**新落点在 /my/apps** |
| ⑤ p5_acd「静音后成绩提醒不到达」 | **脚本判据陈旧（绝对基线）+ 该脚本有卫生 bug** | 断言取**全历史** `event_key=grade_result` 且 `create_date > 2026-08-29` 的计数、要求 ==0 —— 实际历史数百条 ⇒ 永不成立；同脚本"恢复后到达"是 PASS（说明静音/恢复本身工作）。**卫生 bug**：它"全部静音"会把**所有**键置 muted，恢复只覆盖部分键 ⇒ 污染后续脚本（正是①的根因） | 静态"链自洽"✓；失败在判据与卫生，不在产品 |

### 26.1 三类根因（可复用的判读模式）
1. **共享状态污染**（①）：跨脚本留下的偏好/水位会伪装成"功能没触发"；判据：查"是否有人把它静音/改过"。
2. **绝对基线断言**（③⑤）：断言"恰好 1 条 / 恰好 0 条"在共享库上永不成立；应改**基线增量**（先记 t0 与计数，再断言增量）。
3. **页面迁移**（②④）：v3 把旧首页的卡片/收藏迁到 `/my/apps`；断言仍指 `/my/home` 就必然红。

### 26.2 建议（**脚本侧**，交 owner；本任务不改业务代码也未改这些脚本）
| 脚本 | 建议 | 优先级 |
|---|---|---|
| p5_acd_smoke | ① 断言改基线增量；② **保存并恢复完整偏好快照**（现在只恢复部分键 → 污染他人） | 高（它是①的污染源） |
| aux2_batch_smoke | 断言改基线增量（`MARKS_MSG` 增量 1） | 中 |
| ux_batch4_a1_approval_smoke | ① 断言页面改 `/my/apps`（或两页都查）；② 修 rc 语义（rc 应与 FAIL 数一致） | 中 |
| aux3_batch_smoke | 断言页面改 `/my/apps` | 中 |

**产品侧：本次 5 条未发现真缺陷 ⇒ 不需要立"修复任务"**（这本身就是结论：它们全是脚本侧问题）。

---

## 27. M9 收口：全站 axe 无障碍审计（t105，2026-09-14）

**量具**：`scripts/check_accessibility.py`（axe-core **4.10.2** 经 playwright 注入；axe 缓存于 `/tmp/edu_axe/`，
扫描期**不需要联网**）；退出码契约 **0=在基线内 / 1=selftest或工具自身失败 / 2=ENV（axe 取不到·站点不可达·浏览器起不来）/ 3=INCOMPLETE（有页面未扫到）**；
自证行 `REVISION · 运行时指纹 · 断言数 · 运行时刻`，并额外打印**并发状态**（四件套）。

**先证量具再读数（selftest 9/9 PASS）**：必然违规样本页 → **5 条违规**且命中预期规则
（`image-alt`/`html-has-lang`/`color-contrast`/`label`/`link-name`）；**无障碍正确页 → 0 条**（证明不是"什么都报"）。

### 27.1 取样口径（写死在脚本 AUDIT_ROUTES，便于复核）
公开 **6**（`/`、`/programs`、`/admissions`、`/help`、`/login`、`/register`）
＋ 学生 **8**（`/my/home`、`/my/apps`、`/my/study`、`/my/fees`、`/my/time_off`、`/student/timetable`、`/my/messages`、`/downloads`）
＋ 教师 **6** ＋ 家长 **4** ＋ 教务 **4** = **28 页**（覆盖各角色"首页/列表/表单/详情"四类形态）。
**可比性守卫**：只有 **28/28 全扫到**才评估漂移；缺页 ⇒ **INCOMPLETE(3) 且跳过漂移**
（否则"少扫几页 = 总数变小 = 假在基线内"）。这条在实测中确实救了两次：21/28（554 条）与 22/28（483 条）都**没有**被当成基线。

### 27.2 全站读数（基线轮，28/28）
```
违规合计 = 738 条（critical 85 / serious 653 / moderate 0 / minor 0）
color-contrast        serious   x649   例: guest /
select-name           critical  x33    例: student /my/home
button-name           critical  x25    例: student /my/home
label                 critical  x20    例: guest /register
image-alt             critical  x7     例: student /my/apps
link-in-text-block    serious   x3     例: guest /register
link-name             serious   x1     例: student /my/apps
```
四件套：**指纹 71953d4b · 运行时刻 2026-09-14T09:13:39+08:00 · 并发状态 quiet · 退出码 0（在基线内）**；
基线轮（存常量前）为 `超出基线 → 报警`，两条分支都实测过 ✔

### 27.3 基线（常量，漂移即报）
```
BASELINE = {'critical': 85, 'serious': 653, 'moderate': 0, 'minor': 0, 'total': 738, 'pages': 28}
```
与 t53/t96 同机制：**变多即报**（exit 2）；修复后应**下调**本常量（下调属正常，不报警）。

### 27.4 本轮**不修**，修复拆法（供另立任务；建议排在 t104 之后）
| 组 | 规则（条数） | 根因判断 | 建议 inScope | 建议验收 |
|---|---|---|---|---|
| **A 配色令牌（一次性收益最大）** | `color-contrast` 649（88%） | 对比度不足集中在**主题色/次要文字**，属令牌级问题而非逐页问题 | `edu_brand` + `edu_portal` 的 CSS/SCSS 变量（不要逐页改） | 对比度 ≥4.5:1（大字号 ≥3:1）；修后 axe 基线**下调**至实测值，门禁 exit 0 |
| **B 表单控件可访问名** | `select-name` 33 + `label` 20 | 筛选下拉/注册与申请表单的控件缺 `<label>`/`aria-label`；多在**公共 partial**里 | `edu_portal` 表单模板（优先公共 partial，一次改多处） | 两规则归零；新增控件必须带可访问名（写进 code-map §6 约定） |
| **C 图标按钮与图片** | `button-name` 25 + `image-alt` 7 + `link-name` 1 + `link-in-text-block` 3 | 纯图标按钮缺 `aria-label`；图片缺 `alt`（装饰性用 `alt=""`） | `edu_portal`/`edu_brand` 模板 | 四规则归零；约定"图标按钮一律显式命名、图片一律有 alt" |

**修复后的收口动作**：基线常量下调 + `--selftest` 仍绿 + 本门禁 exit 0；可把"新模板过 axe 基线"并入 `docs/code-map.md` §10 闭环（可选）。

### 27.5 已知限制（如实标注）
1. **负载敏感**：重页（`/my/home`、`/my/apps`）在负载下 45s 会超时 ⇒ 已改为 **90s + 一次重试**；三次读数（21/28、22/28、28/28）说明**页面集完整性必须先看**再看总数；
2. **axe 版本固定 4.10.2** 并缓存于 `/tmp`：换版本会改变规则集 ⇒ 换版本必须**同时重设基线**；
3. 覆盖的是**WCAG 2.1 A/AA 的 axe 可判定子集**；键盘可达性、读屏实际朗读、200% 缩放等**不在本量具射程**（需人工/专项）。
---

## 28. A 组收尾独立验证（t118，2026-09-14 12:19–12:29）：color-contrast 归零 + BASELINE 下调 —— **通过**

**取证方式**：同一量具（脚本内容未改，只由 t112 下调过常量）、同一 28 页取样，由 verifier **独立复跑**三件；
**四件套**：指纹 / 运行时刻 / 按规则计数 / 退出码 —— 逐条如下。

### 28.1 四件套读数（本轮实测）
```
① selftest      : == 自证 通过 ==  REVISION=a1 · 指纹 d1e9b15c · 断言 9 条 · 运行时刻 2026-09-14T12:19:35+08:00  SELFTEST_EXIT=0
② 全站审计      : 违规合计 = 87（critical 85 / serious 2 / moderate 0 / minor 0）  扫描成功页 = 28/28
                  color-contrast：**未出现在规则清单中（= 0）**
                  余下规则：select-name 33 / button-name 25 / label 20 / image-alt 7（critical 85）
                            link-in-text-block 1 / link-name 1（serious 2）
                  漂移判定=在基线内  →  **AUDIT_EXIT=0**
                  自证：REVISION=a1 · 指纹 d1e9b15c · 断言 9 条 · 运行时刻 2026-09-14T12:20:06+08:00
                  并发状态=quiet（开跑前 probe=302；宿主负载 14.23 偏高但未致缺页）
③ check_english : TOTAL must-fix = 0 / brand = 0 / 路由状态违规 = 0 / 夹具残留 = 0  →  **EN_EXIT=0**
                  自证：REVISION=v3.6 · 指纹 56c9e514 · 断言 43 条 · 运行时刻 2026-09-14T12:29:26+08:00
```

### 28.2 与 a11y-eng 自报逐项对照

| 项 | a11y-eng 自报 | verifier 实测 | 判定 |
|---|---|---|---|
| 违规合计 | 87 | **87** | ✅ 一致 |
| color-contrast | 0 | **0**（规则清单中不存在） | ✅ 一致 |
| critical / serious | （未逐条报） | **85 / 2** | ✅ 与 BASELINE 构成一致 |
| 页面集 | 28/28 | **28/28** | ✅ 可比轮 |
| 门禁退出码 | exit 0 | **exit 0**（在基线内） | ✅ 一致 |

### 28.3 BASELINE 核对（常量不得高于实测）
```
BASELINE   = {critical: 85, serious: 2, moderate: 0, minor: 0, total: 87, pages: 28}
实测       = {critical: 85, serious: 2, moderate: 0, minor: 0, total: 87, pages: 28}
AUDIT_ROUTES = 28 条（角色集合 = {guest, student, faculty, parent, backoffice}）
可比性守卫   = 在位（comparable = (len(page_rows) == len(AUDIT_ROUTES))）
脚本改动范围 = vs HEAD 仅 2 行非注释变更（serious: 653→2、total: 738→87）
```
→ **常量与实测完全相等**（既不高于、也没留余量）⇒ 从 87 起的任何**新增**违规都会立刻触发漂移报警 ✓；
   且**结构未被改动**（取样清单与可比性守卫都没动），符合"下调只动数值"的口径。
   ⚠ 另一侧的代价也已由机制覆盖：若后续读数**低于** 87（继续修复），门禁仍判"在基线内" ✓，
   但常量应随之再下调，否则会出现与 t118 之前同样的"失明区间"（详见 §27 的 J1）。

### 28.4 ENV / 完整性声明
本轮**未出现缺页**（28/28）、**未出现 ENV**；开跑前 probe=302、并发=quiet（脚本自带 site_ready 探针通过）。
宿主负载 14.23（10 核）偏高但**未造成任何页面超时** —— 按现行判据，页面集完整即读数可比 ✓。
（过程记录：本任务第一次尝试在 12:19 完成 selftest 后被会话中断，**未采信那次不完整的读数**；
  本条结论全部来自 12:20:06/12:29:26 的两次**完整**复跑。）
---

## 29. B+C 收尾独立验证（t121，2026-09-14 13:27–13:29）：**全站 axe = 0** —— 通过

### 29.1 四件套读数（本轮实测）
```
① selftest      : == 自证 通过 ==  REVISION=a1 · 指纹 64e439a8 · 断言 9 条 · 运行时刻 2026-09-14T13:27:04+08:00   SELFTEST_EXIT=0
② 全站审计      : 违规合计 = **0**（critical 0 / serious 0 / moderate 0 / minor 0）  扫描成功页 = **28/28**
                  规则清单为空 ⇒ color-contrast / select-name / label / button-name /
                  image-alt / link-name / link-in-text-block **全部为 0**
                  漂移判定=在基线内  →  **AUDIT_EXIT=0**
                  自证：REVISION=a1 · 指纹 64e439a8 · 断言 9 条 · 运行时刻 2026-09-14T13:27:05+08:00  并发状态=quiet
③ check_english : must-fix 0 / brand 0 / 路由状态违规 0 / 夹具残留 0  →  **EN_EXIT=0**
                  自证：REVISION=v3.6 · 指纹 56c9e514 · 断言 43 条 · 运行时刻 2026-09-14T13:29:25+08:00
```

### 29.2 与实现者自报对照（34 → 0）

| 项 | 自报（C 组提交） | verifier 实测 | 判定 |
|---|---|---|---|
| 违规合计 | 34 → **0** | **0** | ✅ 一致 |
| button-name / image-alt / link-name / link-in-text-block | 25 / 7 / 1 / 1 → **0** | 规则清单为空 ⇒ **全为 0** | ✅ 一致 |
| color-contrast / select-name / label（不得回退） | 保持 0 | **0**（仍不在清单中） | ✅ 无回退 |
| 页面集 | 28/28 | **28/28** | ✅ 可比轮 |
| 门禁退出码 | exit 0 | **exit 0** | ✅ 一致 |

### 29.3 「只动常量」的证据（diff 视图，不是看指纹）
```
工作区 vs HEAD      : **干净**（git diff 为空）——占位的是"最近一次改该文件的提交"
最近提交            : 2266192 feat(a11y): C 组收口 —— 全站 axe 违规 34→0 …
该提交的非注释 diff  : 仅 3 行常量
   - 'critical': 32,        + 'critical': 0,
   - 'serious': 2,          + 'serious': 0,
   - 'total': 34,           + 'total': 0,
改动规模            : 7 insertions(+), 3 deletions(-)（其余全是注释）
BASELINE            : {critical 0, serious 0, moderate 0, minor 0, total 0, pages 28}
```
→ **单看指纹确实分不出"改常量"与"改逻辑"**（本文件指纹从 8ff6b22c 变为 64e439a8，但唯一变更只是常量+注释）
   —— 这正是本条验收要求 diff 视图的理由；本轮据 diff 判定：**结构（AUDIT_ROUTES / 可比性守卫 / axe 运行逻辑）未被改动** ✓

### 29.4 BASELINE 核对与"零余量"含义
常量 `{0, 0, 0, 0, 0, pages 28}` 与实测 `{0, 0, 0, 0, 0, 28}` **完全一致**；
**零余量** ⇒ 此后**任何一条**新违规都会立刻触发漂移报警（这正是我们要的终态）；
反向提醒：若将来因**规则集/axe 版本**变化（如升 axe）导致数字变动，按 §27.5 约定**必须同时重设基线**，不要把版本变化当回归。

### 29.5 ENV / 完整性声明
本轮**无缺页（28/28）、无 ENV**；开跑前 probe=302、并发=quiet、宿主负载 **4.63**（低，条件优于前几轮）。
三件的退出码：SELFTEST_EXIT=0 / AUDIT_EXIT=0 / EN_EXIT=0。
---

## 30. t125 独立验证（取代 t123）：t67 批量作用域提示 / t90 三条冒烟 / t124 manifest 覆盖 —— 全部**通过**，含 2 条如实 findings

**取证方式**：不采信执行者自述；每项先产出**我自己的读数**（命令 + 退出码 + 关键输出）再与执行者并列。

### 30.1 ① 三项我自己产生的读数

**t67 三条批量路由（faculty@local 实测；越权载体为我自建的 【冒烟】 夹具，student 7 不在其作用域）**
```
① leave     MIX: 303 bulk_ok=0&bulk_fail=0&bulk_skip=1&bulk_ignored=2
            ONLY-OUT : 303 ignored=1 + 「另有 1 行不在你的处理范围内或已不存在，已跳过」
            ONLY-NONE: 303 ignored=1 + 同一句文案        → status/loc/body_len **全等**
            正对照（pending 198）: bulk_ok=1&ignored=0   ← 范围内照常处理
② grievance MIX: 303 bulk_ok=1&bulk_fail=0&bulk_skip=0&bulk_ignored=2   ← 正对照成立
            ONLY-OUT / ONLY-NONE: 303 ignored=1 + 同一句文案 → **全等**
③ subject   MIX: 303 bulk_ok=0&bulk_fail=1&bulk_skip=0&bulk_ignored=2
            正对照（只发 10）: fail=1 bulk_msg=SR0008：注册单缺少学生…（**数据原因失败，非跳过/非忽略**）
            ONLY-OUT / ONLY-NONE: 303 ignored=1 + 同一句文案 → **全等**
```
**t90 三条冒烟**
```
G_messages_smoke : TOTAL 25 / FAIL 0 / EXIT=0（我的读法：与实现者 25/0/0 一致）
smoke_anon       : EXIT=0（7/7）
smoke_student    : EXIT=0；#10 走「该生无任何可学课程」数据条件分支，证据里写明完整链路无法构造
```
**t124 manifest 检查器**
```
修复前（cb2f45b~1）跑我的夹具 : 盘上缺失 **0** ｜ 断言 **1 条** ｜ 缺失键**未被点名** ｜ EXIT=1
当前 HEAD（指纹 5d20fa01）   : 盘上缺失 **1** ｜ 断言 **2 条** ｜ 缺失键**被点名**（两候选都列出）｜ EXIT=1
真仓库对照                   : 修复前 OK / 断言 100 / exit 0  ↔  当前 OK / 断言 100 / exit 0（逐字一致）
selftest（我自己跑）          : == 反例自检 通过 == EXIT=0（且反例已固化在脚本内 —— 只证明尺子没坏）
```

### 30.2 ② t67：计数可见 + 正对照 + 不可区分（三条全部成立）
- **计数可见**：三条路由的落地页都渲染「另有 N 行不在你的处理范围内或已不存在，已跳过」（含**选课**路由）；
- **正对照**：leave 198 → ok=1；grievance 23 → MIX ok=1；subject 10 → fail=1 且失败原因是 **SR0008 注册单缺少学生**（**数据原因**，不是被跳过/忽略）；
- **不可区分**：三条路由的 ONLY-OUT 与 ONLY-NONE 在 **status / Location / body 长度**上**逐字一致** ⇒ 不泄露存在性 ✓。

> ⚠ **findings（如实）**：实现者自述的「⚠️ 2. enroll 路由只加了计数、未加人读提示」**与当前 HEAD 不符** —— 
> `enroll.py:538` 已有同一句提示，实测选课页也渲染了它 ⇒ 该自述**已过时**（可能被后续补上）。
> 另：我第一轮用 `state=approved` 打申诉路由，命中其早退分支（该路由用 `resolve/reject`）⇒ 我的**探针口径错**（不是产品问题），已改正后重测。

### 30.3 ③ t90：分类依据 + 三条「打断变红」演示（我自己做的）
```
演示 A（smoke_anon #7，副本注入）: DEMO_A2_EXIT=1  [FAIL] #7
  证据: http_final=http://localhost:8069/login?redirect=%2Fmy%2Fhome%3F, status=200, browser_url=同
演示 B（smoke_student #10，副本注入）: DEMO_B2_EXIT=1  [FAIL] #10
  证据: 空态自洽=False, 系统课次数=8, course_links=0
演示 C（G_messages S14c，副本注入 +1→+999）: DEMO_C_EXIT=1  TOTAL 25 FAIL 2  [FAIL] S14c
```
- **分类依据指向现状**：smoke_anon #7 的实测终态为 `/login?redirect=%2Fmy%2Fhome%3F`（HTTP 200）—— 与实现者"v3 合法行为"的判断一致，故判**脚本陈旧**而非产品红；
- **#10** 的现状读数（`空态自洽 + 系统课次数=8 + course_links=0`）说明该生确实无课可学，判**数据条件**成立 ✓。

> ⚠ **findings（如实）**：
> 1. 我**先试过数据侧注入**（临时停用 `edu.lesson`）→ 才发现 `edu.lesson` **根本没有 active 字段**（`KeyError`）⇒ 该次注入**无效、未用作证据**；
>    最终三条演示改用**副本注入**（对 `/tmp` 下的脚本副本改期望值），演示类型据此标注为"副本注入"而非"产品侧注入"。
> 2. **#10 的交叉核对仍是"半覆盖"**：它用裸 SQL 计数 `psql_count("edu_lesson","1=1")`（我实测=8）判断"课次数据整体丢失"，
>    但**未做产品侧注入验证**（要删共享数据才可证伪，代价过高）⇒ 该断言在真实数据丢失场景下的灵敏度**属于未验证面**，已在此声明。

### 30.4 ④ t124：夹具实测 + 未放宽既有判据
夹具为我自建（`/tmp/eduprobe/t125_fx`：`views/missing.xml` 故意不存在 + 一个裸 dict 项），两版对照见 30.1；
**真仓库两版逐字一致** ⇒ **未放宽**既有判据 ✓；selftest 反例虽已固化，但**不替代上面的实测**（两条并列）。

### 30.5 ⑤ 逐条 verdict
| 项 | verdict | 依据 |
|---|---|---|
| t67 批量作用域提示 | **通过** | 三路由计数可见 + 正对照成立 + OUT/NONE 逐字一致（30.2）|
| t90 三条冒烟 | **通过（含 1 处未验证面）** | 三条脚本我自己跑均 EXIT=0；三条断言各有副本注入的红灯演示；#10 交叉核对灵敏度未验证（30.3）|
| t124 manifest 覆盖 | **通过** | 夹具实测 断言 1→2、缺失键被点名；真仓库逐字一致（30.4）|

### 30.6 环境与清场声明
- 本轮读数窗口：probe=302、负载 8.42–9.60、并发脚本 3（t90 冒烟运行期间）；
- **清场**：我自建的 【冒烟】 载体（leave/grievance，student 7）已删；被我改动的状态已还原（leave 198→request、grievance 23→submitted）；
  我造成的 26 条批量审计行已删；`LEFTOVER=0` ✓。
- **未改任何仓库文件**（本任务只读；演示用的脚本副本都在 `/tmp`）。