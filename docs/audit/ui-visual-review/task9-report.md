# task-9：门户肉眼可视缺陷修复（V1/V2/V3/V5/V6/V8）

> 来源：`docs/audit/ui-visual-review/report.md`（队长人眼复核 8 条，其中 6 条交本卡）。
> 全部读数与截图都是 **2026-10-02** 在本机栈（`http://localhost:8069`，`db=edu19`，登录 `stu@local`）实跑的；
> 视口 **390×844（手机）** 与 **1440×900（桌面）**，同页同视口前后各一张。
> **不动**：V4（手机 Tab「修改密码」）、V7（课程 / 课程中心 / 报课选课 三入口）—— 等产品裁定，只登记。

## 0. 结论（每条都有机械读数，不只靠眼睛）

| # | 缺陷 | 改前读数 | 改后读数 | 判定 |
|---|---|---|---|---|
| V1 | 上手清单压在每页标题之上 | 8/8 读数渲染，高 **121px**，`above_heading=true` | 只有 `/my/home`（121px），其余 **6 条 None** | ✅ 修好，功能保留 |
| V2 | 手机「帮助」折两行 | 手机 help **文本 3 行**（Range 矩形数） | **2 行**（手机）/ 2 行（桌面，本来就够宽） | ✅ |
| V3 | 手机搜索 placeholder 截断 | 文本宽 **219px** > 可用 **104px** ⇒ `clipped=true` | **97px** < **101px** ⇒ `clipped=false`；队长独立复核（19:45 浏览器实测）：390×844 → `搜索应用 / 作业`、1440×900 → `搜索应用 / 作业 / 课程 / 公告 / 账单` | ✅ |
| V5 | `/my/home` 两个搜索框 | 可见 search 输入框 **2** 个 | **1** 个 | ✅ |
| V6 | `/my/home` 两个「通知 104」 | 可见「104」文本节点 **2** 个（手机与桌面都是 2） | **1** 个（手机与桌面都是 1） | ✅ |
| V8 | 报课过截止日无提示 | `overdue_notice=None`，页面只有「本轮报课截止：2026年10月1日」 | 页首告警「**本轮报课已于 2026年10月1日 截止。**」+ 班级目录里「已截止」徽标 | ✅ |

截图（改前 / 改后 / 注入对照，同视口同页）：

| 页 | 改前 | 改后 |
|---|---|---|
| `/my/home`（390×844） | [task9-before/phone_home.png](task9-before/phone_home.png) | [task9-final/phone_home.png](task9-final/phone_home.png) |
| `/student/timetable`（390×844） | [task9-before/phone_timetable.png](task9-before/phone_timetable.png) | [task9-final/phone_timetable.png](task9-final/phone_timetable.png) |
| `/subject/enroll`（1440×900） | [task9-before/desk_enroll.png](task9-before/desk_enroll.png) | [task9-final/desk_enroll.png](task9-final/desk_enroll.png) |
| `/my/home`（1440×900） | [task9-before/desk_home.png](task9-before/desk_home.png) | [task9-final/desk_home.png](task9-final/desk_home.png) |

肉眼确认（我自己看 390 宽的改后图）：顶栏「帮助」一行；placeholder 完整显示「搜索应用 / 作业」；
`/student/timetable` 顶部直接是「我的课表」标题（清单不再压在上面）；`/my/home` 上「通知 104」只剩一处；
`/subject/enroll` 页首有黄色「本轮报课已于 2026年10月1日 截止」告警。

## 1. 取证方法（`task9_shots.py`）

```bash
/opt/homebrew/bin/python3 docs/audit/ui-visual-review/task9_shots.py docs/audit/ui-visual-review/task9-final
```

- 登录 `/web/session/authenticate`（`stu@local`）→ cookie 注入浏览器；**BASE 必须用 `localhost`**：
  用 `127.0.0.1` 打开时 cookie（domain=localhost）带不过去，八张图会全是登录页 —— 第一版就踩了这个坑，已修。
- 每个视口 × 每页各一张 PNG + 一份 `readings.json`；屏蔽站外请求（字体 @import 会把 DOMContentLoaded 拖慢）。
- **折行判据用 Range**：`a.getClientRects()` 对 flex 子项恒为 1（实测假阴性 —— 截图明明两行），
  改对文本节点取 `Range.getClientRects()`，行数才等于换行数。
- **截断判据用 canvas measureText**：`<input>` 的 `scrollWidth` 不反映 placeholder 溢出（实测恒等），
  必须用同字体量出文本宽度再与内宽比。

## 2. 逐条：改了什么（都在 `custom_addons/edu_portal/views/`）

### V1 上手清单压标题之上 — `edu_portal_templates.xml`
清单原本在 `.b11-content` 里、`<t t-out="0"/>`（页面本体）**之前**，所以每页最上面都是它（手机 121px ≈ 844 屏的 14%）。
改法：**只在首页渲染**（`t-if="request.httprequest.path in ('/my/home', '/my')"`）。
★ 功能一字未动：`localStorage` 首次逻辑、「我知道了」按钮、四条文案全在；首页依旧会弹。

### V2 手机「帮助」折两行 — `edu_portal_templates.xml`
顶栏那个 `<a href="/my/help">帮助</a>` 加了 `text-nowrap flex-shrink-0`：文字不再断行，被压缩时整块换行（navbar 本身 flex-wrap）。

### V3 手机搜索 placeholder 截断 — `edu_portal_templates.xml`
窄屏（<768px）换短文案「搜索应用 / 作业」，长文案留给桌面；无脚本时保持 HTML 里的长文案 = 原行为不变。
实现：`data-ph-sm` / `data-ph-lg` + 模板里一小段 `matchMedia` 脚本（本仓模板内联脚本是既有做法）。
全量文案仍在 `aria-label="站内搜索（应用 / 作业 / 课程 / 公告 / 账单）"` 里，屏幕阅读器不受影响。

### V5 `/my/home` 两个搜索框 — `batch2.xml`
去掉横幅里那个（它**不是**真搜索：`home_search.js` 只在前端过滤卡片、回车跳第一张），顶栏那个保留（GET `/my/search`，覆盖 11 组内容）。
`home_search.js` 有 `if(!box) return` 守卫 ⇒ 元素不在时自然空转，不报错；文件本身未删（见 §5）。

### V6 `/my/home` 两个「通知 104」 — `batch2.xml`
两处角标：① 顶部「欢迎」迷你头部的铃铛（`.oe-mhead-badge`）② 下方「通知」卡片行头（`badge bg-danger`）。
去掉 ①（铃铛与它的跳转功能保留），② 保留 —— 同一数字说两遍是弱化不是强化。
另：横幅里那个 `.oe-hero-bell-badge`（桌面端可见）也一并去掉了，属同一条去重。

### V8 报课过了截止日没有提示 — `enroll.xml`
页首加黄色告警 + 班级目录里的「已截止」徽标。判据在模板里算，**控制器一字未动**：

```xml
<t t-set="enroll_deadline_raw"
   t-value="request.env['edu.deadline'].sudo().get_raw('edu.enroll.deadline')"/>
<t t-set="enroll_overdue"
   t-value="bool(enroll_deadline_raw) and datetime.date.today().isoformat() &gt; enroll_deadline_raw"/>
```

- `get_raw` 返回 `YYYY-MM-DD`（同格式字符串可直接比大小）；`datetime` 是 QWeb 环境自带
  （实测依据：容器内 `odoo/addons/base/models/ir_qweb.py` 的 `_prepare_environment` 里有 `datetime=safe_eval.datetime`）。
- 判据用 **>** 不是 ≥：`models/registration.py` 的 `EduDeadline` 写明「截止日当天仍在窗口内」。
- 用的是**服务器本地日期**：部署在马来西亚、用户在中国，跨零点有半小时窗口可能差一天；
  该误差方向偏「不算已截止」，不会把还能报的挡掉。

## 3. 反向自证（把修好的还原，缺陷必须回来）

两次都是**真升级**（`safe_upgrade.sh edu_portal` EXIT=0）后重新截图、重新读数，不是纸面推演。

| 注入 | 改后读数 | 注入后读数 | 还原后 |
|---|---|---|---|
| V2：去掉 `text-nowrap flex-shrink-0` | help 文本 **2 行** | help 文本 **3 行**（截图 [task9-inject/phone_home.png](task9-inject/phone_home.png)） | 2 行 |
| V3：`data-ph-sm` 还原成长文案 | placeholder 97px < 101px，`clipped=false` | **219px > 101px，`clipped=true`**（截图 [task9-inject-v3/phone_home.png](task9-inject-v3/phone_home.png)） | `clipped=false` |

> 照实记两点：
> ① 第一次做注入时 `safe_upgrade` 被 gate A（manifest 跟踪）**拒绝**了一次——那是队友正在改文件的瞬时状态，
>    重跑即过；我没有绕过门禁。
> ② V2 第一次注入时我把 `data-ph-*` 一起删了，脚本读到 `undefined` 直接把 placeholder 写成字面量 "undefined" ——
>    这**不是**原缺陷，所以我重做了一次只注入长文案的 V3 对照（上表最后一行），拿到干净的因果。
>    ⚠ **19:38–19:39 之间线上出现过的那个字面量 `undefined` 就是这次注入造成的**（不是产品缺陷、也不是收尾状态）；
>    队长在这一窗口独立看到并提醒，特此对齐：已消失，终态读数是 `搜索应用 / 作业`。
>
> **由此得一条流程教训（队长指出、我认领）**：`safe_upgrade.sh` 是把**当前文件**快照进库的 ——
> 「改到一半就升级」会把半成品真的暴露给用户（本次就是：脚本已入库、`data-ph-*` 还没加）。
> ⇒ 中途升级（含反向注入）**不能只看 EXIT=0，必须再看一眼渲染结果**；本轮每次注入/还原后都重新截图读数，所以第一时间自己发现并纠正了。

## 4. 门禁与升级

```bash
$ bash scripts/safe_upgrade.sh edu_portal
[safe_upgrade] 结束：edu_portal（无失败特征；完整日志 /tmp/edu19_upgrade.20261002-193828.log）
SAFE_UPGRADE_EXIT=0        # 本轮共跑了 4 次 safe_upgrade(edu_portal)，每次 EXIT=0、失败特征 0 条

$ /opt/homebrew/bin/python3 scripts/check_ui_usability.py --report
（读数见 §4.1；要求 A/B/C/D 四轴 0 命中且样本有效=True —— V1/V3 改的正是顶栏与首页，必须复验）
```

### 4.1 D 轴复验（V1/V3 动过 `edu_portal_templates.xml`，队长明确要求复跑）

```
$ docker inspect -f 'StartedAt-before={{.State.StartedAt}}' edu19-clone-web-1
StartedAt-before=2026-10-02T11:39:17.431004672Z
$ /opt/homebrew/bin/python3 scripts/check_ui_usability.py --report       # 2026-10-02T19:39:31+08:00
================ 汇总 ================
探页 148 条 = 99 页 × 身份；探到 142 ｜ 非环境失败 0 ｜ 环境失败 0 ｜ 排除 31
命中（原始）：A 0 ｜ B 0 ｜ C 0 ｜ D 0 = 0 条；去重键 0 个（报红 0 条 / 0 页）
读数落盘：tests/ui/readings/usability-20261002-1941.json（指纹 4f53cda18c2baa0c）
采集时刻 2026-10-02T19:39:31+08:00 ｜ 并发 quiet ｜ 容器 edu19-clone-web-1
  （StartedAt 2026-10-02T11:39:17.431004672Z -> 2026-10-02T11:39:17.431004672Z，样本有效=True）
-- 当前全部命中（--report：不与基线比对）（0 条）--
   （无）
$ docker inspect -f 'StartedAt-after={{.State.StartedAt}}' edu19-clone-web-1
StartedAt-after=2026-10-02T11:39:17.431004672Z      # 前后逐字相同 ⇒ 样本有效
```

⇒ **A 0 ｜ B 0 ｜ C 0 ｜ D 0 = 0 命中，样本有效=True**（手机顶栏与首页正是 V1/V2/V3/V5/V6 动过的地方）。

## 5. 没做的事 / 副作用（照实列）

| 项 | 说明 |
|---|---|
| V4、V7 | 未动（产品裁定项），仅在队长报告里登记 |
| `home_search.js` | 本卡交付时它变成空转（守卫保护、无报错），我**没有删文件**并在原报告里留了「要不要恢复」的裁定点。
  ⇒ **队长已裁定（6072f00）：删掉**（连带 manifest 条目与 batch2 注释），理由是本仓不为「万一以后要用」保留死代码；要恢复用 git 历史取回 |
| 桌面 placeholder 截断 | 本卡交付时**桌面同样截断**（输入框内宽 150px vs 26 字 219px，只是断在「课程」之后）。
  ⇒ **队长已裁定（6072f00）：两档都收短**（手机 `搜索应用 / 作业`、桌面 `搜索应用 / 作业 / 课程`），完整 5 组枚举留在 `aria-label`。
  我按交付后的实况**独立复测**（`task9-postfollow/readings.json`）：手机 97px<101px、桌面 **137px<150px**，两档 `clipped=false`，与队长读数一致 |
| 横幅搜索的卡片即时过滤 | 随 V5 一起去掉了（两个入口长得一样、行为不同才是缺陷根源）。若产品要它，建议**只保留**横幅那个并让顶栏不再显示搜索框 |

## 5.1 收尾（队长复核定案，2026-10-02）

- 本卡交付提交：**f5745fa**（含全部证据图）；队长独立复测结论与本报告一致（`/my/home` 清单 h=121 且其余三页缺失、
  `/my/home` 可见搜索框 =1、`/subject/enroll` 含「已截止」+ `2026年10月1日`）。
- 我留的两个裁定点由队长拍定并落地：**6072f00** —— ① 桌面 placeholder 也收短到排得下的完整短句；② `home_search.js` 删除（含 manifest 与注释）。
- 连锁修复（队长做）：`#searchBox` 移除后 `tests/smoke/E_quiz_cross.py` 的 B7 会变成**必然 WARN**（再也变不红），
  已改成查**现存活且唯一**的顶栏入口（次数 ==1、`action=/my/search`），现在 PASS 且可红。
  —— 这正是本仓「不能变红的门禁是假门禁」那条纪律的一次现场应用：**删掉被断言的对象，等于悄悄废掉一条断言**，必须同步改判据。

> 我的自我认领（`undefined` 中途态）被队长写进了提交说明；本节把「本卡交付态 → 队长裁定 → 交付后实况」三层分清，
> 避免以后有人拿这份报告当「桌面仍截断 / JS 仍在」的证据。

## 6. 复跑命令

```bash
# 截图 + 读数（手机 390×844 / 桌面 1440×900，登录 stu@local）
/opt/homebrew/bin/python3 docs/audit/ui-visual-review/task9_shots.py <输出目录>
# 逐条读数对比（readings.json 里 help.search_inputs[].clipped / number_badges["104"] / onboard / overdue_notice）
python3 -c "import json;print(json.load(open('<输出目录>/readings.json')))"
```
