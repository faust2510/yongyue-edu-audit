#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可用性门禁：把「看得见的缺陷」变成可重跑的判据（四轴 · 机械可判定）。

背景（为什么要有这条门禁）
--------------------------
七轴体检（docs/audit/ui-gap-ledger.md，731 行）的结论是：**现有三个 UI 门禁
（route_matrix / accessibility / english）在结构上抓不到「按钮跑出屏幕」这类可用性缺陷** ——
它们量的是「不 5xx / 不大面积 404」「英文词表」「axe 无障碍」，判据里没有一条是
「元素在不在视口内」。两条独立证据：
  (a) 已覆盖的对照组问题率**反而更高**（35% vs 死角组 27%）= 覆盖度不等于质量；
  (b) 对照组自己就带着一条 P1 —— /leave/approvals 在 375 视口横向溢出，
      「批准」按钮 rect 超出视口 ⇒ 手机上审批请假要横滑才能按。
⇒ 只把覆盖补全，这类问题下次照样漏。本脚本把**机械可判定的四条轴**变成判据。

⚠️ 怎么跑（**必须先读这条，否则会以为门禁坏了**）
------------------------------------------------
仓里默认的 `python3` 是 **3.9，没有 playwright**。带 playwright 的解释器是：
```
/opt/homebrew/bin/python3          # 3.14.6 ← 优先用这个
/Users/qwe/miniconda3/bin/python3  # 3.13.13（备选）
```
所以调用一律写全路径，例：
```
/opt/homebrew/bin/python3 scripts/check_ui_usability.py --selftest
/opt/homebrew/bin/python3 scripts/check_ui_usability.py --baseline   # 冻结存量
/opt/homebrew/bin/python3 scripts/check_ui_usability.py --check      # 只报新增/恶化（ratchet）
/opt/homebrew/bin/python3 scripts/check_ui_usability.py --report     # 打印全部命中
```
它**不进** `docs/code-map.md` §10 的「0 离线自证」链（那一段要求零环境依赖、停机可跑）；
本门禁需要**活站点 + 浏览器**，属「周期性 + 部署前」那一层。分工见 `tests/smoke/UX_V3_GATE.md`。

四条轴（判据必须客观、可复算；判断型的轴留在周期性人工体检里，不进脚本）
----------------------------------------------------------------------
  A 横向溢出    375 视口下 document.documentElement.scrollWidth - clientWidth > 阈值（默认 8px）
                ⇒ 报红，给出溢出像素数。
  B 主操作横向越界  button / .btn / a.btn 的 bounding rect
                **只判横向**：right > 视口宽，或 left < 0 ⇒ 报红，给出元素文本 + rect。
                纵向只保留一种真缺陷：bottom < 0（整块被定位到文档上方，看不见也够不着）。
                ⚠️ 为什么**不**判「下边界超出视口高」：长页面里按钮落在折叠线以下是**完全正常**的 ——
                实测误报过一次：/leave/approvals 上 9 个按钮全被判红，理由都是「下溢 2645~2680px」。
                （不可见元素 = offsetWidth/offsetHeight 均为 0 ⇒ 不判，避免折叠菜单里的假红。）
  C 中文措辞错   tests/ui/wording.json 里对照表命中的**错词** ⇒ 报红，给出命中文本与所在页。
                匹配口径（刻意的，防假红）：**元素自身文本**（直接文本子节点、空白归一后）**逐字等于**
                错词，且该元素本身不是交互控件（button/a/select/option/input/textarea）。
                为什么不用 substring：仓内「还没有任何下载记录。」「本次没有任何改动。」「经过二十余年
                的发展」都是**合法中文**，substring 会把它们判成机翻错词 —— 判据一有噪声，人就开始
                忽略红灯。逐字相等只命中「token 级机翻」这一类真缺陷（下拉项 / 状态列 / 表头），
                而实测的三条命中（解决 / 拒绝 / CMP 日期）都恰好是 dropdown-item 里的 span。
  D 空态无出口   页面无列表行（table tbody tr）**且**无卡片（.card）⇒ 判为空态；若此时页内
                **没有任何指向其他页面**的 a[href] ⇒ 报红（死胡同）。局限照实说：这是「结构性空态」
                的粗判（不看文案），只抓「空 + 无出口」的极端死胡同；空态质量分级仍属人工体检
                （docs/ux-audit.md §3.3）。

数据来源（**不另写名单**）
--------------------------
  · 页面清单：tests/ui/surface.json 里 scope=="portal" 的条目（A 组维护的登记表）。表读不到 ⇒
    退出码 3（INCOMPLETE），**不退回写死名单** —— 那等于把刚拆掉的第二份名单重新长出来。
  · 参数化路由（<int:task_id> 等）：**不裸探**，实例从既有读数 tests/ui/readings/dead-45.json 的
    (path_template -> 已实测具体 path) 取；没有实例 ⇒ 记 skipped(no-instance)，不猜 id、不造 id。
  · 措辞对照表：tests/ui/wording.json（每条都在仓内有实测出处，note 里写明）。

取样口径（用哪个身份打开哪一页 —— 表里没有等价字段，留在这里）
--------------------------------------------------------------
  · **一页 1–2 个身份**：登记表里第一个本脚本有会话的身份；若该页还登记了 faculty/backoffice
    且与前者不同，再加**一个**教务/教师身份。理由是本轮实测出来的盲区：/leave/approvals 学生
    视图 overflow=0，**教师视图 126px**（已知 P1 就在这里）—— 只探一个身份会把这类「学生能打开、
    缺陷只在教师视图」的问题整片漏掉。登记表的角色数组不是受众优先级（它把 student 排在最前），
    所以口径不能只取「第一个」。
  · ⚠ **默认口径有已知盲区，且已实证**（2026-10-02）：上限 2 个身份意味着**同一路径只看了部分受众**。
    实证：`/my/fees` 只抽中 `faculty`，而**教师身份下账单表根本不渲染** ⇒ A 轴读数 0；
    同一页以**学生**身份打开时横向溢出 **93px**（表格 453px 且无 .table-responsive 包裹）。
    ⇒ 默认模式保留快速 ratchet（148 条）；要「整页无死角」跑 **`--all-roles`**（238 条，约 1.6 倍）：
      它把每页登记的**全部**可登录身份都探一遍，实测把 `/my/fees` 从 1 个身份扩到 3 个（faculty/parent/student）。
    ⚠ 两种模式**样本集不同，读数不可直接比大小**，`--all-roles` 的结论要单独陈述、不要拿去与基线做 ratchet。
  · 无任何可登录身份 ⇒ anon（guest，不带 cookie）；页面清单里没有 admin 账号。
  · 路径含下载响应（/my/documents/transcript 等）⇒ Playwright 报 Download is starting：这不是
    "探失败"，是**它不是可判定的页面**（无视口可量）⇒ 记 skipped(download-not-a-page)。
  · **非 HTML 响应同此口径**（2026-09-28 加，判据见 is_judgeable_page）：登记表里混着
    **JSON 数据端点**（/my/notice_banner：Content-Type application/json、body {"banners": []}、
    全站 a[href] 指向它 0 次、只有 JS data-fetch 拉取）。它不是页面，D 轴「空态无出口」
    判它是**结构性误报** ⇒ 记 skipped(not-a-page(<ctype>))，不判任何轴。
    为什么不在 surface.json 里改判：那张表由 ui_surface_report.py 生成，merge_rows() 只保留
    gates/status/roles/key，kind/scope 每次重算 —— 手改会被静默覆盖，口径只能落在门禁侧。
  · **采样期间容器重启 ⇒ 样本作废（ENV，退出码 2）**：探页前后各读一次 web 容器 StartedAt，
    不一致就明说「样本作废」，绝不把重启窗口里的读数当基线（UX_V3_GATE.md §0 的纪律）。

⛔ 红线（本脚本的硬约束）
------------------------
  1. **有副作用的路由一律不探**：路径含 SIDE_EFFECT_TOKENS 的**不发请求**；另外
     /attendance/selfcheck/<token> 也排除（名字不含禁用词，但 GET 里写考勤）。
     被排除的在读数里记 skipped(side-effect-guard)。
  2. **只读探本机栈** http://localhost:8069：单次 GET / 页（请求落在 Playwright 导航里，
     不额外 curl 一遍），不循环重试、不写库、不升级、不重启、不碰生产。
  3. 只读仓内文件（surface.json / wording.json / dead-45.json），绝不改它们。

机制（照本仓门禁惯例）
----------------------
  · --baseline：把**当前**读数冻结成基线（tests/ui/readings/usability-baseline.json）。
    存量问题先记账、不阻断 —— 这是 ratchet 的起点。
  · --check：与基线比对，**只报新增/恶化**（同键 metric 变大 = 恶化）；改善只报 INFO、不报红。
    断言里带**采集时刻 + 基线指纹**（读数不带时刻就不许引用）。
  · --report：打印全部当前命中（不带基线比对），同时落一份带时刻的读数。
  · **每 30 条探页重启一次 browser**（2026-09-28 队长裁定）：/my/study 在门禁里连续 3 轮
    30s 超时，隔离复测却 6 次全绿、requests 直取 200/0.3–0.6s、docker logs 无慢请求；
    复现实验（先建 100 个 context 再探它）得到 0.69s / **30.01s(超时)** / 0.68s
    ⇒ 量具（Playwright/Chrome）context 累积失真，不是页面缺陷。
    处理方式是**重置量具**：重启 browser 继续探，**不加重试、不调单页超时**
    （那会把「量具坏了」和「实物真慢」混成一个读数）。重启次数与重启点记进
    readings 的 meta.probe_engine，结论行也自报 —— 见 BROWSER_RESTART_EVERY。
  · --selftest：**先证量具再读数**。纯函数断言 + **真实页面**正负对照 ——
    正样本 /leave/approvals（已知 375 视口横向溢出 + 「批准」按钮出视口）必须报红；
    负样本 /my/password（实测干净页）必须一条都不报。selftest 不过则不采信任何读数。
  · 退出码：0=无新增/改善 ｜ 1=有新增或恶化 ｜ 2=ENV（站点不可达 / 浏览器起不来）
             ｜ 3=INCOMPLETE（surface.json 读不到 / 有页没探到）

用法（⚠ 解释器必须写全路径，见下）
    /opt/homebrew/bin/python3 scripts/check_ui_usability.py --list      # 只读打印名单与排除账（不连站点）
    /opt/homebrew/bin/python3 scripts/check_ui_usability.py --selftest  # 证量具（含两条真实页面正负对照）
    /opt/homebrew/bin/python3 scripts/check_ui_usability.py --report    # 全量现探 + 打印全部命中
    /opt/homebrew/bin/python3 scripts/check_ui_usability.py --baseline  # 冻结当前读数为基线
    /opt/homebrew/bin/python3 scripts/check_ui_usability.py --check     # 与基线比对（周期性重跑 / CI 用）

⚠ 解释器（本机实测 2026-09-28，务必照用，否则会误判「门禁坏了」）
------------------------------------------------------------------
本脚本 import playwright。**裸 `python3` 在不同 shell 下解析到不同解释器**，其中一支没有
playwright ⇒ 直接 ModuleNotFoundError: No module named 'playwright'，看起来像脚本坏了，
其实是解释器选错：

    bash -lc 'which python3; python3 -V'   →  /usr/bin/python3           →  Python 3.9.6   ✗ 无 playwright
    zsh  -lc 'which python3; python3 -V'   →  /opt/homebrew/bin/python3  →  Python 3.14.6  ✓ 有 playwright

因此**一律写全路径**，优先：

    /opt/homebrew/bin/python3          # 3.14.6（体检组实测跑通，首选）
    /Users/qwe/miniconda3/bin/python3  # 3.13.13（备选，同样 import 得到 playwright）

（依赖 Playwright 的其它脚本同此口径，如 tests/smoke/ux_v3_route_matrix.py 的视口轴。）
UX_V3_GATE.md §0.1 有同一份说明；改了这里的口径请同步那一节。
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time

import requests
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SURFACE = 'tests/ui/surface.json'
WORDING = 'tests/ui/wording.json'
DEAD_READINGS = 'tests/ui/readings/dead-45.json'
BASELINE_PATH = 'tests/ui/readings/usability-baseline.json'
READINGS_DIR = 'tests/ui/readings'

BASE = 'http://localhost:8069'
DB = 'edu19'

REVISION = 'v1.0 · 2026-09-26 七轴体检收口：A/B/C/D 四轴门禁（真实页面正负自证 + ratchet 基线）'
RUN_STAMP = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
SELFTEST_CASES = 0            # 由 selftest() 实际计数，末尾与断言总数比对（防悄悄少证）

# ---- 阈值（命令行可覆盖；写进读数与基线，便于复算）----
VIEWPORT_W = 375
VIEWPORT_H = 812
OVERFLOW_PX = 8               # A：溢出 > 8px 才算（1–2px 的 rounding 噪声不算病）
BUTTON_BOTTOM_FACTOR = 0      # 【作废】B 轴曾用「下边界 > 视口高 ×1.5」，实测在长页上误报 9 个按钮
                              #   （折叠线下方 2645px 是正常的）。现只判横向 + bottom<0；
                              #   键保留只为读数/基线的形状兼容，不再参与判据。
BROWSER_RESTART_EVERY = 30    # 每探 N 条**重启一次浏览器**（重置量具，不是重试）
                              # 为什么（2026-09-28 实测，队长裁定按「每 30 页重启」实现）：
                              #   /my/study 在门禁里连续 3 轮 30s 超时，而隔离复测 6 次全绿
                              #   （0.44–0.70s）、requests 直取 200/0.3–0.6s、docker logs 无慢请求；
                              #   复现实验：干净浏览器第 1 次 0.67s → 先建 100 个 context 各加载
                              #   一页 → 再探 /my/study：0.69s(ok) / **30.01s(超时)** / 0.68s(ok)。
                              #   ⇒ Playwright/Chrome 侧的量具失真，不是页面缺陷。
                              # ⚠ 2026-09-28 二次定位（重启**不能完全消除**，如实记下）：
                              #   在门禁 30s 超时的同一窗口里，从本机直连 /my/study（requests）
                              #   最慢 0.38s ⇒ 服务端没问题；给超时那一次的 Playwright 挂上
                              #   request 监听，卡住时**唯一未收到响应的请求**是
                              #   https://fonts.googleapis.com/css?family=Roboto:…
                              #   —— 它来自 Odoo website 模块注入前端资产包的无阻塞 @import
                              #   （/web/assets/.../web.assets_frontend.min.css 里实测含该行；
                              #   website/models/assets.py:251 由站点字体配置生成），
                              #   而 @import 未落地会让样式表「没加载完」→ 其后的脚本被挡
                              #   → **DOMContentLoaded 一直不触发**。
                              #   重启用的是「换一个干净 browser」，它能压低概率但消不掉这条
                              #   外网依赖；要彻底确定化得在门禁里屏蔽外网请求（会改变字体
                              #   度量 ⇒ 可能动 A 轴读数，属口径变更，需另行裁定，未做）。
                              # 为什么不加单页重试、不调高单页超时：那会把「量具坏了」和
                              #   「实物真慢」混成一个读数 —— 本仓反复吃过这个亏。
                              #   重启是**恢复量具**，读数仍然是每页单次 GET。
WORSEN_TOLERANCE = 8          # ratchet 的「恶化」容差（px）。理由是本轮实测出来的：
                              #   同一页 /leave/approvals 在同一小时内两次探到 139px 与 126px ——
                              #   本机栈是共享的、演示数据会变（行数/徽章变 ⇒ 溢出量跟着变）。
                              #   容差 0 会把这种数据抖动报成"恶化"，而**新增/消失的键**才是
                              #   真正可信的信号（页面/元素从"没事"变成"有事"）。容差可命令行覆盖。

# ---- 取样身份（与 check_accessibility.py 同一套演示账号；本脚本无 admin/anon 会话）----
ROLE_LOGINS = {
    'student': ('stu@local', 'demo123'),
    'faculty': ('faculty@local', 'demo123'),
    'parent': ('parent@local', 'demo123'),
    'backoffice': ('backoffice@local', 'demo123'),
}
STAFF_ROLES = ('faculty', 'backoffice')      # 「教务/教师」侧身份（第二个取样身份从这里取）
ALL_ROLES = False            # --all-roles：**不设上限**，把每页登记的全部可登录身份都探一遍。
                             #   为什么要有这个模式（2026-10-02 实测，不是理论担忧）：
                             #   默认口径「一页 1–2 个身份」会漏掉**只对某个身份才渲染出来**的缺陷。
                             #   实证：/my/fees 只抽中 faculty，而教师身份下账单表**根本不渲染**
                             #   ⇒ A 轴读数为 0；同一页以**学生**身份打开，横向溢出 **93px**
                             #   （表格 453px 且无 .table-responsive 包裹）。
                             #   ⇒ 默认保持快速 ratchet（约 148 条探页）；
                             #     要「整页无死角」时跑 --all-roles（条数 2–3 倍，20 分钟量级）。
                             #   ⚠ 两种模式的读数**不可直接比大小**（样本集不同）——
                             #     --all-roles 的结论要单独陈述，别拿去和默认基线做 ratchet。
ROLE_ANON = 'guest'

# ---- 红线 1：副作用守卫（逐字照体检组已定的判据）----
SIDE_EFFECT_TOKENS = (
    'deactivate', 'confirm', 'save', 'submit', 'delete', 'remove', 'cancel', 'close',
    'approve', 'reject', 'transfer', 'import', 'apply', 'start', 'stop', 'send', 'mark',
    'join', 'poll',
)
# 名字不含禁用词、但 GET 里写考勤（体检组实测确认）
EXTRA_SKIP = {
    '/attendance/selfcheck/<token>': 'side-effect-guard',
}
# 注：approvals **不**含子串 approve（approve = a-p-p-r-o-v-e），所以 /leave/approvals 与
#     /registrar/subject/approvals 仍会被探 —— 这是刻意的：/leave/approvals 正是本门禁的
#     正样本（已知 375 溢出 + 「批准」按钮出视口）。selftest 有断言守着这条口径。

DYN_SEG_RE = re.compile(r'<[^>]+>')

DEF_AXES = ('A', 'B', 'C', 'D')
AXIS_NAMES = {'A': '横向溢出', 'B': '主操作不在视口内', 'C': '中文措辞错', 'D': '空态无出口'}


def _self_fingerprint():
    """自身文件 md5 前 8 位（运行时算；不靠人 bump）。"""
    with open(os.path.abspath(__file__), 'rb') as fh:
        return hashlib.md5(fh.read()).hexdigest()[:8]


def self_attest_line():
    return 'REVISION=%s · 指纹 %s · 断言 %d 条 · 运行时刻 %s' % (
        REVISION, _self_fingerprint(), SELFTEST_CASES, RUN_STAMP)


def repo_path(rel):
    return os.path.join(REPO, rel.replace('/', os.sep))


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def stamp_compact():
    return datetime.datetime.now().strftime('%Y%m%d-%H%M')


# ---------------------------------------------------------------- 名单：surface.json（单一来源）
def load_surface():
    """读 tests/ui/surface.json 里 scope=='portal' 的条目。返回 (rows, err)。"""
    p = repo_path(SURFACE)
    if not os.path.exists(p):
        return [], 'surface.json 不存在'
    try:
        with open(p, encoding='utf-8') as fh:
            doc = json.load(fh)
    except Exception as e:
        return [], 'surface.json 读不动（%s）' % e
    rows = []
    for it in (doc.get('pages') or []):
        if it.get('scope') != 'portal':
            continue
        path = it.get('path') or ''
        if not path.startswith('/'):
            continue
        rows.append({'path': path, 'roles': sorted(it.get('roles') or []),
                     'module': it.get('module') or '', 'key': it.get('key') or ''})
    rows.sort(key=lambda r: r['path'])
    return rows, None


def browser_restart_points(n, every=BROWSER_RESTART_EVERY):
    """计划长度 n 时，「重启浏览器」发生在第几条探页**之前**（1-based；第 1 条前不重启）。

    纯函数（selftest 直接喂夹具），probe_all 也用它 —— 计划与执行同一处口径。
    例：n=137、every=30 ⇒ [31, 61, 91, 121]（共 4 次重启、5 个浏览器实例）。
    """
    if every <= 0:
        return []
    return [i for i in range(1, n + 1) if i > 1 and (i - 1) % every == 0]


def instance_ok(reading):
    """一条读数能不能当「参数化路由的实例」（**纯函数**，selftest 直接喂夹具）。

    两条都要满足：
      ① path 里没有动态段 —— 读数是模板（没真探过）就不算实例；
      ② 读数自身的 **final 状态是成功**（200/303）。
    ⚠ ② 是 2026-09-28 补的，事故现场：/my/reimburse/receipt/<bill>/<att> 的实例取到了
      /my/reimburse/receipt/1/1 —— 而这条在来源表 dead-45.json 里**本来就是实测 404**
      （本地没有报销单收据：edu_fee_bill_receipt_rel 0 行、附件 id=1 是 res.lang 的国旗图）。
      拿它当样本 = 门禁自己造了一条**必然 404** 的探页，还会让人误以为「路由坏了」。
      没有可用实例 ⇒ 走既有 skipped(no-instance)：不猜 id、不造 id。
    """
    path = reading.get('path') or ''
    if not path or DYN_SEG_RE.search(path):
        return False
    return (reading.get('http') or {}).get('final') in (200, 303)


def load_instances():
    """参数化模板 -> 既有读数里**实测过且真能打开**的具体路径（dead-45.json）。

    不猜 id、不造 id：实例只从别人已经探过并落盘的读数里取（同一栈、同一批数据），
    且必须通过 instance_ok()（无动态段 + final ∈ {200,303}）。
    """
    out = {}
    p = repo_path(DEAD_READINGS)
    if not os.path.exists(p):
        return out
    try:
        with open(p, encoding='utf-8') as fh:
            doc = json.load(fh)
    except Exception:
        return out
    for r in (doc.get('readings') or []):
        tpl = r.get('path_template')
        if not tpl or not instance_ok(r):
            continue
        out.setdefault(tpl, r['path'])
    return out


def side_effect_reason(path):
    """红线 1：这条路要不要跳。返回 None（可探）或跳过原因。"""
    if path in EXTRA_SKIP:
        return EXTRA_SKIP[path]
    low = path.lower()
    for tok in SIDE_EFFECT_TOKENS:
        if tok in low:
            return 'side-effect-guard'
    return None


def pick_roles(roles):
    """一页取 1–2 个身份（口径见文件头 §取样口径）。

    ① 登记表**第一个**本脚本有会话的身份（原样尊重登记顺序）；
    ② 若该页还登记了 faculty/backoffice 且与 ① 不同 ⇒ 再补**第一个**staff 身份。
    上限 2 个：共享栈上"把每页 × 全部身份"扫一遍会把单轮时间翻四倍，而收益集中在 ② 这条
    （学生的页面 + 只对教师可见的操作）。宁可少扫身份、也要把少扫这件事写在这里。
    """
    avail = [r for r in roles if r in ROLE_LOGINS]
    if not avail:
        return [ROLE_ANON]
    if ALL_ROLES:
        # --all-roles：不做取舍，登记了几个可登录身份就探几个（见常量注释里的实测理由）
        return list(avail)
    picked = [avail[0]]
    for r in avail:
        if r in STAFF_ROLES and r not in picked:
            picked.append(r)
            break
    return picked


def build_plan(rows, instances):
    """(可探清单, 排除账)。可探项 = 一条 (身份 × 路径)；排除项逐条写明原因。"""
    probe, skipped = [], []
    for row in rows:
        tpl = row['path']
        why = side_effect_reason(tpl)          # 红线 1 优先：有副作用就不探（原因也记它）
        if not why and DYN_SEG_RE.search(tpl) and not instances.get(tpl):
            for role in pick_roles(row['roles']):
                skipped.append({'path': tpl, 'role': role, 'skipped': 'no-instance'})
            continue
        real = instances.get(tpl, tpl) if DYN_SEG_RE.search(tpl) else tpl
        src = 'surface.json + dead-45 实例' if DYN_SEG_RE.search(tpl) else 'surface.json'
        for role in pick_roles(row['roles']):
            if why:
                skipped.append({'path': tpl, 'role': role, 'skipped': why})
                continue
            probe.append({'role': role, 'path_template': tpl, 'path': real, 'src': src})
    return probe, skipped


# ---------------------------------------------------------------- 措辞对照表
def load_wording():
    p = repo_path(WORDING)
    if not os.path.exists(p):
        return [], 'wording.json 不存在'
    try:
        with open(p, encoding='utf-8') as fh:
            rows = json.load(fh)
    except Exception as e:
        return [], 'wording.json 读不动（%s）' % e
    out = []
    for it in rows or []:
        bad, good = (it.get('bad') or '').strip(), (it.get('good') or '').strip()
        if bad:
            out.append({'bad': bad, 'good': good, 'note': (it.get('note') or '').strip()})
    return out, None


# ---------------------------------------------------------------- 采集（浏览器内单次 GET）
MEASURE_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const doc = document.documentElement;
  const buttons = [];
  document.querySelectorAll('button, .btn, a.btn').forEach(el => {
    if (!el.offsetWidth && !el.offsetHeight) return;      // 不可见（折叠菜单/隐藏）⇒ 不判
    const r = el.getBoundingClientRect();
    buttons.push({text: norm(el.innerText || el.textContent).slice(0, 40),
                  tag: el.tagName.toLowerCase(),
                  cls: (el.className || '').toString().slice(0, 60),
                  left: Math.round(r.left), right: Math.round(r.right),
                  top: Math.round(r.top), bottom: Math.round(r.bottom)});
  });
  const SKIP = {BUTTON: 1, A: 1, SELECT: 1, OPTION: 1, INPUT: 1, TEXTAREA: 1,
                SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TITLE: 1};
  const texts = [];
  document.querySelectorAll('body *').forEach(el => {
    if (SKIP[el.tagName]) return;                          // 交互控件不判措辞（见 C 轴口径）
    let t = '';
    el.childNodes.forEach(n => { if (n.nodeType === 3) t += n.textContent; });
    t = norm(t);
    if (!t || t.length > 30) return;
    texts.push({text: t, tag: el.tagName.toLowerCase(),
                cls: (el.className || '').toString().slice(0, 60)});
  });
  const links = [];
  document.querySelectorAll('a[href]').forEach(a => links.push(a.getAttribute('href')));
  const q = s => document.querySelectorAll(s).length;
  return {viewport: {w: window.innerWidth, h: window.innerHeight},
          scroll_width: doc.scrollWidth, client_width: doc.clientWidth,
          title: document.title,
          rows: q('table tbody tr'), cards: q('.card'),
          forms: q('form'), tables: q('table'), inputs: q('input, textarea, select'),
          buttons: buttons, texts: texts, links: links};
}
"""


def _norm_path(href):
    """href -> 站内路径（去 query/fragment）；不是站内页则 None（锚点/mailto/tel/javascript）。"""
    if not href:
        return None
    h = href.strip()
    if h.startswith(('#', 'mailto:', 'tel:', 'javascript:', 'data:')):
        return None
    if h.startswith('http://') or h.startswith('https://'):
        m = re.match(r'^https?://[^/]+(/.*)?$', h)
        if not m:
            return None
        h = m.group(1) or '/'
    if not h.startswith('/'):
        return None
    return h.split('#')[0].split('?')[0].rstrip('/') or '/'


def is_judgeable_page(ctype):
    """响应是不是「可判定的页面」：只有 text/html 才有视口 / 文案 / 出口可量。

    为什么要有这条（2026-09-28）：/my/notice_banner 是 **JSON 数据端点**
    （Content-Type: application/json、body {"banners": []}；全站 a[href] 指向它 0 次，
    只有 JS 的 data-fetch 拉取）——D 轴「空态无出口」把它当页面判是**结构性误报**
    （D 只做粗判，门禁自述的局限）。口径与既有的 download-not-a-page 一致：
    不是可判定的页面 ⇒ 记 skipped(not-a-page)，**不判任何轴**，也不进 findings。
    探不到 content-type（空串）时**按页面判**：宁可报存量，不缩判据。
    """
    if not ctype:
        return True
    return 'html' in ctype.split(';')[0].strip().lower()


def probe_verdict(ctype, state, cur_path, thresholds, wording, role='-'):
    """探页判决（**纯函数**）：非 HTML ⇒ None（=skipped，不判任何轴）；HTML ⇒ judge()。

    把「跳不跳」与「怎么判」分成两个纯函数，是为了让 selftest 能直接用夹具证两件事：
    ① 正样本：application/json 的夹具 ⇒ 不产生任何 findings；
    ② 反样本：text/html 的空态页夹具 ⇒ 仍然报 D（收紧口径不许误伤真缺陷）。
    """
    if not is_judgeable_page(ctype):
        return None
    return judge(state, cur_path, thresholds, wording, role)


def judge(state, cur_path, thresholds, wording, role='-'):
    """四条轴 -> findings。纯函数（selftest 直接喂夹具，不连站点）。

    key 里**必须**带身份：同一路径对不同身份渲染不同，少了身份两个身份的读数会撞成一个键。
    """
    findings = []
    tag = '%s|%s' % (role, cur_path)
    vw, vh = state['viewport']['w'], state['viewport']['h']

    # A 横向溢出
    overflow = state['scroll_width'] - state['client_width']
    if overflow > thresholds['overflow_px']:
        findings.append({'axis': 'A', 'key': 'A|%s' % tag, 'metric': overflow,
                         'detail': '375 视口下文档横向溢出 %dpx（scrollWidth %d - clientWidth %d > %d）'
                                   % (overflow, state['scroll_width'],
                                      state['client_width'], thresholds['overflow_px'])})

    # B 主操作**横向**越界（只判横向）
    # 为什么不判纵向：长页面里按钮落在折叠线以下是**完全正常**的 ——
    # 实测过一次误报：/leave/approvals 上 9 个按钮全被判红，理由都是「下溢 2645~2680px」。
    # 纵向只保留一种真缺陷：整块被定位到文档上方（bottom < 0 —— 看不见也够不着）。
    for b in state['buttons']:
        # 只有「与视口**横向相交**、却又没被完全容纳」的控件才算真越界。
        # 为什么要这道闸：a11y 的 skip-link（「跳至内容」）**本就该在视口外** ——
        # 实测它 rect(left -1, right 0)，宽 1px，被「left<0」直接误抓。
        # 完全落在视口之外的（off-canvas 抽屉、left:-9999 的藏件）一律不判：
        # 那些是「设计上不在屏内」，不是「控件跑出屏幕」。
        intersects_x = b['right'] > 0 and b['left'] < vw
        if not intersects_x:
            continue
        over_r = b['right'] - vw
        over_l = -b['left']
        off_top = b['bottom'] < 0
        if over_r > 0 or over_l > 0 or off_top:
            findings.append({
                'axis': 'B',
                'key': 'B|%s|%s' % (tag, b['text'] or ('<%s>' % b['tag'])),
                'metric': max(over_r, over_l),
                'text': b['text'],
                'detail': '%s「%s」横向越界：rect(left %d, right %d, top %d, bottom %d)，'
                          '视口宽 %d（右溢 %dpx / 左溢 %dpx%s）'
                          % (b['tag'], b['text'] or '（无文本）', b['left'], b['right'],
                             b['top'], b['bottom'], vw,
                             max(over_r, 0), max(over_l, 0),
                             ('；且整块位于文档上方 bottom=%d<0' % b['bottom']) if off_top else ''),
            })

    # C 中文措辞错（逐字相等 + 元素本身非交互控件）
    for w in wording:
        hits = [t for t in state['texts'] if t['text'] == w['bad']]
        if hits:
            findings.append({'axis': 'C', 'key': 'C|%s|%s' % (tag, w['bad']),
                             'metric': len(hits), 'text': w['bad'],
                             'detail': '命中错词「%s」（应为「%s」）%d 处，例：<%s class="%s">'
                                       % (w['bad'], w['good'], len(hits),
                                          hits[0]['tag'], hits[0]['cls'])})

    # D 空态无出口
    if state['rows'] == 0 and state['cards'] == 0:
        others = {p for p in (_norm_path(h) for h in state['links'])
                  if p and p != cur_path}
        if not others:
            findings.append({'axis': 'D', 'key': 'D|%s' % tag, 'metric': 0,
                             'detail': '空态（无列表行 / 无卡片）且页内没有任何指向其他页面的 a[href]'
                                       '（站内链接 %d 条，去重后 0 条）' % len(state['links'])})
    return findings


# ---------------------------------------------------------------- 环境证据（只读 docker，不改容器）
def web_container():
    """找 web 容器名（只读 docker ps）。找不到 ⇒ None（少一层证据，不阻塞）。"""
    try:
        out = subprocess.run(['docker', 'ps', '--format', '{{.Names}}'],
                             capture_output=True, text=True, timeout=15)
        for n in (out.stdout or '').split():
            if n.endswith('web-1'):
                return n
    except Exception:
        return None
    return None


def container_started_at(name):
    """web 容器 StartedAt（只读 docker inspect）。采样前后各读一次 —— UX_V3_GATE §0 的纪律：
    重启窗口里的读数不算数（本轮实测就在采样中途撞上一次重启 ⇒ 5 页 CONNECTION_RESET）。"""
    if not name:
        return None
    try:
        out = subprocess.run(['docker', 'inspect', '-f', '{{.State.StartedAt}}', name],
                             capture_output=True, text=True, timeout=15)
        return (out.stdout or '').strip() or None
    except Exception:
        return None


CONN_ERR_RE = re.compile(r'ERR_CONNECTION|ERR_EMPTY_RESPONSE|ERR_SOCKET|ERR_TIMED_OUT'
                         r'|ERR_NAME_NOT_RESOLVED|ERR_NETWORK_CHANGED')


# ---------------------------------------------------------------- 探页
def login_session(role):
    """角色 -> requests 会话（只为拿 session_id cookie，请求本身与探页无关）。"""
    s = requests.Session()
    s.trust_env = False
    if role in ROLE_LOGINS:
        login, pwd = ROLE_LOGINS[role]
        try:
            s.post(BASE + '/web/session/authenticate',
                   json={'jsonrpc': '2.0',
                         'params': {'db': DB, 'login': login, 'password': pwd}}, timeout=25)
        except Exception:
            pass
    return s


def probe_all(plan, thresholds, wording, log=print):
    """逐条 (身份 × 路径) 单次 GET + 375 视口测量。

    返回 (readings, failed, env_failed, dl_skipped, conc, started, ctr)：
      · failed     = 探页失败（非环境原因）=> INCOMPLETE(3)
      · env_failed = 连接层失败（容器重启/掉线）=> ENV(2)，**不是判据红**
      · dl_skipped = **不是页面**的响应（无视口可量）=> skipped(...)：两条来源
                    · download-not-a-page      下载响应（Playwright 报 Download is starting）
                    · not-a-page(<ctype>)      非 HTML 数据端点，如 /my/notice_banner 的
                                               application/json（见 is_judgeable_page）
      · ctr        = 采样窗口前后 web 容器 StartedAt 对账（不一致 => 样本作废）
    """
    conc, _busy = concurrency_note()
    sessions = {}
    readings, failed, env_failed, dl_skipped = [], [], [], []
    started = now_iso()
    ctr = {'name': web_container(), 'before': None, 'after': None, 'sample_valid': None}
    ctr['before'] = container_started_at(ctr['name'])
    restarts = []
    restart_points = set(browser_restart_points(len(plan)))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', headless=True, args=['--no-proxy-server'])
        for i, item in enumerate(plan, 1):
            if i in restart_points:
                # 重置量具（不是重试）：扔掉累积的 browser 进程，换一个干净的继续探。
                # 读数仍是每页单次 GET —— 不重试、不调超时（见 BROWSER_RESTART_EVERY 注释）。
                browser.close()
                browser = pw.chromium.launch(channel='chrome', headless=True,
                                             args=['--no-proxy-server'])
                restarts.append(i)
                log('  -- 重置量具：第 %d/%d 条前重启 browser（每 %d 条一次，防 context 累积）'
                    % (i, len(plan), BROWSER_RESTART_EVERY))
            role, path = item['role'], item['path']
            if role not in sessions:
                sessions[role] = login_session(role)
            cookie = sessions[role].cookies.get('session_id')
            ctx = browser.new_context(viewport={'width': thresholds['vpx'],
                                                'height': thresholds['vpy']})
            if cookie:
                ctx.add_cookies([{'name': 'session_id', 'value': cookie,
                                  'domain': 'localhost', 'path': '/'}])
            page = ctx.new_page()
            t0 = time.time()
            try:
                resp = page.goto(BASE + path, wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(250)          # 等首屏布局稳定（不是轮询、不重试）
                state = page.evaluate(MEASURE_JS)
                status = resp.status if resp else None
                ctype = ''
                try:
                    ctype = (resp.headers or {}).get('content-type', '')
                except Exception:
                    ctype = ''
                final_path = page.url.split('8069')[-1] or '/'
                body_len = len(page.content() or '')
            except Exception as e:
                ctx.close()
                msg = str(e)
                if 'Download is starting' in msg:
                    dl_skipped.append({'path': path, 'role': role,
                                       'skipped': 'download-not-a-page'})
                    log('  [%3d/%3d] %-9s %-40s v 下载响应（不是页面，跳过）'
                        % (i, len(plan), role, path))
                elif CONN_ERR_RE.search(msg):
                    env_failed.append({'path': path, 'role': role, 'error': msg[:160]})
                    log('  [%3d/%3d] %-9s %-40s ! ENV %s'
                        % (i, len(plan), role, path, msg[:60]))
                else:
                    failed.append({'path': path, 'role': role, 'error': msg[:160]})
                    log('  [%3d/%3d] %-9s %-40s x %s' % (i, len(plan), role, path, msg[:70]))
                continue
            ms = int((time.time() - t0) * 1000)
            findings = probe_verdict(ctype, state, _norm_path(final_path),
                                     thresholds, wording, role)
            if findings is None:
                # 非 HTML 响应 ⇒ 不是可判定的页面（JSON 数据端点 / 文本 / 图片…）：
                # 与 download-not-a-page 同口径记 skipped，不判任何轴、不落 findings。
                main_type = (ctype or '').split(';')[0].strip().lower() or 'unknown'
                dl_skipped.append({'path': path, 'role': role,
                                   'skipped': 'not-a-page(%s)' % main_type})
                ctx.close()
                log('  [%3d/%3d] %-9s %-40s v 非 HTML 响应（%s，不是页面，跳过）'
                    % (i, len(plan), role, path, main_type))
                continue
            vp_key = 'viewport_%d' % thresholds['vpx']
            readings.append({
                'path': path,
                'path_template': item['path_template'],
                'role': role,
                'set': 'usability-portal',
                'authorized': 'anon' if role == ROLE_ANON else 'yes',
                'source': item['src'],
                'http': {'first': status, 'hist': [], 'final': status,
                         'final_path': final_path, 'ctype': ctype,
                         'disposition': '', 'marks': [], 'bytes': body_len, 'ms': ms},
                'viewport': {
                    vp_key: {'overflow_px': state['scroll_width'] - state['client_width'],
                             'scroll_width': state['scroll_width'],
                             'client_width': state['client_width'],
                             'buttons': [{'text': b['text'], 'left': b['left'],
                                          'right': b['right'], 'top': b['top'],
                                          'bottom': b['bottom'],
                                          'inX': b['right'] <= thresholds['vpx']}
                                         for b in state['buttons']]},
                    'collected_at': now_iso(),
                },
                'key_elements_found': {
                    'forms': state['forms'], 'tables': state['tables'], 'inputs': state['inputs'],
                    'rows': state['rows'], 'cards': state['cards'],
                    'outbound_links': len({p for p in
                                           (_norm_path(h) for h in state['links']) if p}),
                    'empty_state': (state['rows'] == 0 and state['cards'] == 0),
                    'buttons': [b['text'] for b in state['buttons']][:20],
                    'content_links': sorted({p for p in
                                             (_norm_path(h) for h in state['links']) if p})[:8],
                },
                'findings': findings,
                'verdict': 'red' if findings else 'green',
                'notes': ('最终页 %s（%s）' % (final_path, status))
                         if _norm_path(final_path) != _norm_path(path) else '',
            })
            ctx.close()
            flag = ' '.join(sorted({f['axis'] for f in findings})) or '-'
            log('  [%3d/%3d] %-9s %-40s %s %4dms ov=%-4d 命中=%s'
                % (i, len(plan), role, path, status, ms,
                   readings[-1]['viewport'][vp_key]['overflow_px'], flag))
        browser.close()
    ctr['after'] = container_started_at(ctr['name'])
    ctr['sample_valid'] = (ctr['before'] is None or ctr['after'] is None
                           or ctr['before'] == ctr['after'])
    engine = {'browser': 'chrome (channel=chrome, headless)',
              'restart_every': BROWSER_RESTART_EVERY,
              'browser_restarts': len(restarts),
              'restarted_before_probe': restarts,
              'probes': len(plan),
              'policy': '重置量具：每 %d 条重启 browser；不重试、不调单页超时'
                        % BROWSER_RESTART_EVERY}
    return readings, failed, env_failed, dl_skipped, conc, started, ctr, engine


def site_ready():
    """站点就绪探针（同一 Session + trust_env=False：否则环境代理会把本地站点判成不可达）。"""
    s = requests.Session()
    s.trust_env = False
    try:
        r = s.get(BASE + '/web/login?db=' + DB, timeout=15, allow_redirects=False)
        return r.status_code in (200, 302, 303)
    except Exception:
        return False


def concurrency_note():
    """并发状态：此刻是否有别的冒烟/门禁在跑（共享栈，读数要记这个）。"""
    try:
        out = subprocess.run(['ps', '-ef'], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return 'unknown', []
    hits = [l.strip()[:90] for l in (out or '').splitlines()
            if (('tests/smoke/' in l) or ('scripts/check_' in l))
            and 'grep' not in l and 'check_ui_usability' not in l]
    return ('busy' if hits else 'quiet'), hits


# ---------------------------------------------------------------- 汇总 / 基线
def axis_counts(readings):
    c = {a: 0 for a in DEF_AXES}
    for r in readings:
        for f in r.get('findings') or []:
            c[f['axis']] = c.get(f['axis'], 0) + 1
    return c


def findings_payload(readings):
    """findings -> **按 key 去重**的清单（同一页同类命中合并成 1 条）。

    去重是必要的：/leave/approvals 一个 12 行的表格里，「批准」按钮每一行都出视口 ⇒
    原始命中 45 条、去重后 4 条（批准/驳回/详情/转交）。ratchet 要的是**可比对的键**，
    不是行数；occurrences 保留"有几处在报"，metric 取**最差那一处**（恶化时它才动）。
    """
    agg = {}
    for r in readings:
        for f in r.get('findings') or []:
            k = f['key']
            if k in agg:
                agg[k]['occurrences'] += 1
                if f['metric'] > agg[k]['metric']:
                    agg[k]['metric'] = f['metric']
                    agg[k]['detail'] = f['detail']
            else:
                agg[k] = {'key': k, 'axis': f['axis'], 'path': r['path'],
                          'path_template': r['path_template'], 'role': r['role'],
                          'metric': f['metric'], 'text': f.get('text', ''),
                          'detail': f['detail'], 'occurrences': 1}
    out = sorted(agg.values(), key=lambda x: (x['axis'], x['path'], x['key']))
    return out


def payload_fingerprint(items):
    blob = json.dumps(items, ensure_ascii=False, sort_keys=True).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()[:16]


def build_doc(readings, skipped, failed, conc, thresholds, stamps, ctr=None, env_failed=None,
              engine=None):
    """读数文档（形状照 tests/ui/readings/dead-45.json：meta + readings + 逐条 collected_at）。"""
    items = findings_payload(readings)
    ctr = ctr or {}
    red = [r for r in readings if r['verdict'] == 'red']
    return {
        'meta': {
            'group': 'usability',
            'source': '%s (scope=portal) + %s' % (SURFACE, WORDING),
            'axes': 'A 横向溢出 / B 主操作不在视口内 / C 中文措辞错 / D 空态无出口',
            'thresholds': thresholds,
            'collected_at': {'probe': stamps['started'], 'finish': now_iso(),
                             'tool': RUN_STAMP},
            'tool': {'script': 'scripts/check_ui_usability.py', 'revision': REVISION,
                     'fingerprint': _self_fingerprint()},
            'counts': {'paths': len({r['path'] for r in readings}),
                       'probes': len(readings),
                       'skipped': len(skipped), 'failed': len(failed),
                       'env_failed': len(env_failed or []),
                       'red_probes': len(red), 'red_paths': len({r['path'] for r in red}),
                       'axes': axis_counts(readings)},
            'concurrency': conc,
            'container': ctr,
            # 探页引擎记账：browser 重启次数与重启点（「重置量具」口径，见 BROWSER_RESTART_EVERY）。
            # 记进读数是为了下次看到超时/异常时，先能判断量具是否已按纪律重置过。
            'probe_engine': engine or {},
        },
        'readings': readings + [dict(s, verdict='skipped', findings=[]) for s in skipped],
        'axes': axis_counts(readings),
        'findings': items,
        'fingerprint': payload_fingerprint(items),
    }


def write_readings(doc, tag=None):
    os.makedirs(repo_path(READINGS_DIR), exist_ok=True)
    name = 'usability-%s%s.json' % (stamp_compact(), ('-' + tag) if tag else '')
    p = repo_path(os.path.join(READINGS_DIR, name))
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    return p


def load_baseline():
    p = repo_path(BASELINE_PATH)
    if not os.path.exists(p):
        return None, '基线文件不存在（先跑 --baseline 冻结存量）'
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh), None
    except Exception as e:
        return None, '基线文件读不动（%s）' % e


def compare(cur_items, base_items, tolerance=0):
    """ratchet：只报新增 / 恶化（同键 metric 超出容差才算恶化）。改善只报 INFO。"""
    base = {i['key']: i for i in base_items}
    cur = {i['key']: i for i in cur_items}
    new = [cur[k] for k in cur if k not in base]
    worse = [{'cur': cur[k], 'base': base[k]} for k in cur
             if k in base and cur[k]['metric'] > base[k]['metric'] + tolerance]
    gone = [base[k] for k in base if k not in cur]
    return new, worse, gone


def print_findings(items, title):
    print('-- %s（%d 条）--' % (title, len(items)))
    for it in items:
        occ = ('×%d ' % it['occurrences']) if it.get('occurrences', 1) > 1 else ''
        print('   [%s·%s] %-38s %s%s' % (it['axis'], AXIS_NAMES[it['axis']], it['path'], occ,
                                         it['detail']))
    if not items:
        print('   （无）')


def env_verdict(env_failed, ctr):
    """环境层判决：样本作废 => (2, 说明)；否则 (0, '')。

    ENV 不是 FAIL：连接层失败/容器重启说明**这一轮的读数不作数**，既不判绿也不判红。
    """
    if ctr.get('sample_valid') is False:
        return 2, ('ENV：采样期间 web 容器重启（StartedAt %s -> %s）=> **样本作废**，'
                   '不判定、不冻结基线（UX_V3_GATE.md §0 纪律）'
                   % (ctr.get('before'), ctr.get('after')))
    if env_failed:
        return 2, ('ENV：%d 条探页撞上连接层失败（容器重启/掉线）=> 样本作废：%s'
                   % (len(env_failed), [e['path'] for e in env_failed[:4]]))
    return 0, ''


# ---------------------------------------------------------------- 自证
def selftest():
    """先证量具：纯函数断言 + 真实页面正负对照。"""
    global SELFTEST_CASES
    emitted = 0

    def check(label, got, want, note=''):
        nonlocal emitted
        good = (got == want)
        emitted += 1
        print('  %s %-34s 期望 %s 实际 %s%s'
              % ('PASS' if good else 'FAIL', label, want, got, ('  ' + note) if note else ''))
        return good

    ok = True
    print('== 自证 ①：纯函数口径（不连站点）==')
    # 红线 1：副作用守卫 + 「approvals 不被 approve 误伤」这条关键口径
    for label, path, want in (
            ('guard:import 跳过', '/attendance/import', 'side-effect-guard'),
            ('guard:transfer 跳过', '/leave/transfer', 'side-effect-guard'),
            ('guard:save 跳过', '/my/checkin/save', 'side-effect-guard'),
            ('guard:poll 跳过', '/my/messages/poll', 'side-effect-guard'),
            ('guard:selfcheck 跳过', '/attendance/selfcheck/<token>', 'side-effect-guard'),
            ('guard:approvals 仍可探', '/leave/approvals', None),
            ('guard:password 仍可探', '/my/password', None)):
        ok = check(label, side_effect_reason(path), want,
                   'approvals 不含子串 approve，不被误伤' if path == '/leave/approvals' else '') and ok

    th = {'vpx': 375, 'vpy': 812, 'overflow_px': 8, 'button_bottom_factor': 1.5}
    base = {'viewport': {'w': 375, 'h': 812}, 'scroll_width': 375, 'client_width': 375,
            'buttons': [], 'texts': [], 'links': ['/my/home'], 'rows': 1, 'cards': 0}
    # A 轴阈值边界
    ok = check('A:溢出 8px 不报', len(judge(dict(base, scroll_width=383), '/p', th, [])), 0) and ok
    ok = check('A:溢出 9px 报 1 条', len(judge(dict(base, scroll_width=384), '/p', th, [])), 1) and ok
    ok = check('A:报出的像素数',
               [f['metric'] for f in judge(dict(base, scroll_width=505), '/p', th, [])
                if f['axis'] == 'A'], [130]) and ok
    # B 轴：**只判横向**（右出界 / 左被切） ＋ 唯一真纵向缺陷 bottom<0
    # 「纵向在折叠线以下」**不是缺陷**：旧判据按「下边界 > 视口高×1.5」判，
    # 实测在 /leave/approvals 上误报 9 个按钮（下溢 2645px —— 那只是页面长）。
    btn = lambda **kw: dict({'text': '批准', 'tag': 'button', 'cls': '', 'left': 300,
                             'right': 448, 'top': 700, 'bottom': 740}, **kw)
    ok = check('B:右边界 448>375 报', len(judge(dict(base, buttons=[btn()]), '/p', th, [])), 1) and ok
    ok = check('B:纵向在折叠线以下不报（旧判据假红①）',
               len(judge(dict(base, buttons=[btn(left=10, right=100, top=1200, bottom=1300)]),
                         '/p', th, [])), 0, '实测自 /leave/approvals 的 9 个假红') and ok
    ok = check('B:左边被切（部分出界）报',
               len(judge(dict(base, buttons=[btn(left=-30, right=50, top=10, bottom=44)]),
                         '/p', th, [])), 1) and ok
    ok = check('B:完全在视口外不报（skip-link/off-canvas，旧判据假红②）',
               len(judge(dict(base, buttons=[btn(left=-9999, right=-9879, top=0, bottom=30)]),
                         '/p', th, [])), 0, '实测自 /my/password 的「跳至内容」') and ok
    ok = check('B:bottom<0（被定位到文档上方）报',
               len(judge(dict(base, buttons=[btn(left=10, right=100, top=-60, bottom=-10)]),
                         '/p', th, [])), 1) and ok
    ok = check('B:完全在视口内不报',
               len(judge(dict(base, buttons=[btn(left=10, right=100, top=10, bottom=44)]),
                         '/p', th, [])), 0) and ok
    # C 轴：逐字相等口径（仓内合法中文不得被 substring 误伤）
    W = [{'bad': '经过', 'good': '及格', 'note': ''}]
    ok = check('C:长句含错词不报（防假红）',
               len([f for f in judge(dict(base, texts=[{'text': '经过二十余年的发展', 'tag': 'p',
                                                        'cls': ''}]), '/p', th, W)
                    if f['axis'] == 'C']), 0) and ok
    ok = check('C:逐字相等才报',
               len([f for f in judge(dict(base, texts=[{'text': '经过', 'tag': 'td', 'cls': ''}]),
                                     '/p', th, W) if f['axis'] == 'C']), 1) and ok
    # D 轴：空态定义 + 出口
    ok = check('D:空态且无站内出口报',
               len([f for f in judge(dict(base, rows=0, cards=0,
                                          links=['#top', 'mailto:a@b.c', '/p']), '/p', th, [])
                    if f['axis'] == 'D']), 1) and ok
    ok = check('D:空态但有出口不报',
               len([f for f in judge(dict(base, rows=0, cards=0, links=['/my/home']), '/p',
                                     th, []) if f['axis'] == 'D']), 0) and ok
    ok = check('D:有卡片不当空态',
               len([f for f in judge(dict(base, rows=0, cards=1), '/p', th, [])
                    if f['axis'] == 'D']), 0) and ok
    # ── 页面判定：非 HTML 响应不是「可判定的页面」（2026-09-28 加）──
    # 事故现场：/my/notice_banner 是 JSON 数据端点（application/json、{"banners": []}、
    # 全站 a[href] 指向它 0 次），D 轴把它当页面判「空态无出口」= 结构性误报。
    # 空态夹具：无列表行 / 无卡片 / **没有指向其他页面的站内链接**（#top 与 mailto 不算出口）
    empty_state = dict(base, rows=0, cards=0, links=['#top', 'mailto:a@b.c'])
    ok = check('page:application/json 不是可判页面',
               is_judgeable_page('application/json; charset=utf-8'), False) and ok
    ok = check('page:text/html 是可判页面',
               is_judgeable_page('text/html;charset=utf-8'), True) and ok
    ok = check('page:探不到 content-type 时按页面判（不缩判据）',
               is_judgeable_page(''), True) and ok
    # 正样本（夹具）：JSON 响应 ⇒ 一条 findings 都不产生（skip 点 = probe_verdict 返回 None）
    ok = check('page:[正]JSON 夹具不产生任何 findings',
               probe_verdict('application/json', empty_state, '/not-a-page', th, []) is None, True,
               '与 download-not-a-page 同口径：记 skipped，不判任何轴') and ok
    # 反样本（夹具）：同一个空态 DOM，只要响应是 HTML ⇒ D 轴照旧报（收紧口径不许误伤真缺陷）
    ok = check('page:[反]HTML 空态夹具仍然报 D',
               len([f for f in (probe_verdict('text/html', empty_state, '/empty', th, []) or [])
                    if f['axis'] == 'D']), 1) and ok

    # ── 探页引擎：每 N 条重启 browser（2026-09-28 加；重置量具，不是重试）──
    e = browser_restart_points(137, 30)
    ok = check('engine:137 条 / 每 30 条 => 重启 4 次', e, [31, 61, 91, 121]) and ok
    ok = check('engine:恰好 30 条不重启', browser_restart_points(30, 30), []) and ok
    ok = check('engine:第 31 条前重启一次', browser_restart_points(31, 30), [31]) and ok
    ok = check('engine:第 1 条前永不重启', browser_restart_points(1, 30), []) and ok
    ok = check('engine:every<=0 视为不重启', browser_restart_points(100, 0), []) and ok
    ok = check('engine:收窄到 2 条计划 => 0 次重启',
               len(browser_restart_points(2, BROWSER_RESTART_EVERY)), 0,
               'selftest 真实页对照只有 2 条，读数里浏览器重启数应为 0') and ok

    # 名单 / 实例来源
    inst = load_instances()
    ok = check('instances:读到 dead-45 实例', bool(inst.get('/assess/fill/<int:task_id>')), True,
               '例=%s' % inst.get('/assess/fill/<int:task_id>')) and ok
    ok = check('instances:模板不当实例',
               DYN_SEG_RE.search(inst.get('/assess/fill/<int:task_id>') or '') is None, True) and ok
    # ── 实例来源收紧：只有「真能打开」的读数才算实例（2026-09-28 加）──
    # 事故现场：dead-45.json 里 /my/reimburse/receipt/1/1 **本来就是实测 404**
    # （本地无报销单收据：edu_fee_bill_receipt_rel 0 行、附件 id=1 是 res.lang 国旗图）。
    ok = check('instances:200 读数被采纳',
               instance_ok({'path': '/a/1', 'http': {'final': 200}}), True) and ok
    ok = check('instances:303 读数被采纳',
               instance_ok({'path': '/a/1', 'http': {'final': 303}}), True) and ok
    ok = check('instances:404 读数**不被**采纳',
               instance_ok({'path': '/my/reimburse/receipt/1/1',
                            'http': {'final': 404}}), False,
               '来源读数是死角表，里面就录着 404 的行') and ok
    ok = check('instances:无状态读数不被采纳',
               instance_ok({'path': '/a/1'}), False) and ok
    ok = check('instances:模板不当实例（与状态无关）',
               instance_ok({'path': '/a/<int:x>', 'http': {'final': 200}}), False) and ok
    ok = check('instances:本轮 dead-45 里 404 那条确实不被采纳',
               '/my/reimburse/receipt/<int:bill_id>/<int:att_id>' not in inst, True,
               '该模板将走既有 skipped(no-instance)') and ok
    rows, err = load_surface()
    ok = check('surface:读得到 portal 名单', (err is None and len(rows) > 0), True,
               'portal=%d' % len(rows)) and ok
    ok = check('surface:名单路径合法', all(r['path'].startswith('/') for r in rows), True) and ok
    wording, werr = load_wording()
    ok = check('wording:读得到对照表', (werr is None and len(wording) > 0), True,
               '%d 条' % len(wording)) and ok
    # ratchet 判定（纯函数）
    ok = check('ratchet:相同不报', compare([{'key': 'A|/x', 'metric': 10}],
                                           [{'key': 'A|/x', 'metric': 10}])[:2],
               ([], [])) and ok
    ok = check('ratchet:变大=恶化', [len(x) for x in compare([{'key': 'A|/x', 'metric': 12}],
                                                             [{'key': 'A|/x', 'metric': 10}])[:2]],
               [0, 1]) and ok
    ok = check('ratchet:新键=新增/旧键=改善',
               [len(x) for x in compare([{'key': 'A|/y', 'metric': 1}],
                                        [{'key': 'A|/x', 'metric': 10}])][::2],
               [1, 1]) and ok
    ok = check('ratchet:容差内抖动不报恶化',
               len(compare([{'key': 'A|/x', 'metric': 130}], [{'key': 'A|/x', 'metric': 126}],
                           tolerance=8)[1]), 0, '139↔126px 是本轮实测到的同页抖动') and ok

    print('')
    print('== 自证 ②：真实页面正负对照（连本机栈；这是本门禁的立身之本）==')
    if not site_ready():
        print('  FAIL 站点不可达 %s ⇒ ENV（exit 2）' % BASE)
        print('== 自证 不通过 == %s' % self_attest_line())
        return 2
    pos_path, neg_path = '/leave/approvals', '/my/password'
    probe = [{'role': 'faculty', 'path_template': pos_path, 'path': pos_path,
              'src': 'selftest: 正样本（已知 375 溢出）'},
             {'role': 'student', 'path_template': neg_path, 'path': neg_path,
              'src': 'selftest: 负样本（实测干净页）'}]
    readings, failed, env_failed, _dl, conc, started, ctr, engine = probe_all(
        probe, th, wording)
    if failed or env_failed or ctr.get('sample_valid') is False:
        print('  FAIL 探页失败 %s %s（容器 %s）⇒ ENV（exit 2）'
              % (failed, env_failed, ctr))
        print('== 自证 不通过 == %s' % self_attest_line())
        return 2
    by_path = {r['path']: r for r in readings}
    pos, neg = by_path[pos_path], by_path[neg_path]
    vp_key = 'viewport_375'
    print('  采集时刻 %s ｜ 并发 %s ｜ 基线指纹（本轮读数指纹）%s'
          % (started, conc, payload_fingerprint(findings_payload(readings))))
    dedup = {it['key']: it for it in findings_payload(readings)}
    pos_keys = [it for it in dedup.values() if it['path'] == pos_path]
    print('  正样本 %s（faculty）：overflow=%dpx，原始命中 %d 条 -> 去重键 %d 个，命中轴 %s'
          % (pos_path, pos['viewport'][vp_key]['overflow_px'], len(pos['findings']),
             len(pos_keys), sorted({f['axis'] for f in pos['findings']}) or '无'))
    for it in pos_keys[:4]:
        print('     · [%s×%d] %s' % (it['axis'], it['occurrences'], it['detail']))
    if len(pos_keys) > 4:
        print('     · … 另 %d 个去重键（完整清单见自证读数 JSON）' % (len(pos_keys) - 4))
    print('  负样本 %s（student）：overflow=%dpx，命中轴 %s'
          % (neg_path, neg['viewport'][vp_key]['overflow_px'],
             sorted({f['axis'] for f in neg['findings']}) or '无'))
    # ── 正样本改成**合成夹具**（纯函数 judge 直接喂），真实页只做环境与负样本检查 ──
    # 为什么必须这么改：原先的正样本是**真实 URL /leave/approvals 的横向溢出**，
    # 于是自证依赖「那个 bug 还在」。D 组把它修好（126px→0px）后，「正样本应报红」必然失败 ——
    # 门禁与实物脱节。**门禁的自证必须自给自足**：正样本自己造，真实页只验「渲染得出来 + 干净页确实干净」。
    W = [{'bad': '没有任何', 'good': '不分组'}]
    synth = {'viewport': {'w': 375, 'h': 812}, 'scroll_width': 700, 'client_width': 375,
             'buttons': [{'tag': 'button', 'text': '批准', 'left': 300, 'right': 460,
                          'top': 10, 'bottom': 40}],
             'texts': [{'text': '没有任何', 'tag': 'span', 'cls': ''}],
             'links': ['/my/home'], 'rows': 1, 'cards': 0}
    sf = judge(synth, '/synthetic-wide', th, W, role='student')
    s_axes = {f['axis'] for f in sf}
    ok = check('正样本(合成):横向溢出报红 A', 'A' in s_axes, True) and ok
    a_metric = [f['metric'] for f in sf if f['axis'] == 'A']
    ok = check('正样本(合成):A 像素数 > 阈值', bool(a_metric) and a_metric[0] > th['overflow_px'], True,
               'A=%s' % (a_metric[:1] or ['-'])) and ok
    ok = check('正样本(合成):按钮横向越界报红 B', 'B' in s_axes, True) and ok
    ok = check('正样本(合成):错词报红 C', 'C' in s_axes, True) and ok
    bt = judge(dict(synth, scroll_width=375, buttons=[], texts=[]), '/synthetic-clean', th, W)
    ok = check('负样本(合成):干净夹具一条不报', len(bt), 0) and ok
    # 回归守卫：**长页面里按钮在折叠线以下不许报红**（本轴曾经就是这么刷假红的）
    longpage = dict(synth, scroll_width=375, texts=[],
                    buttons=[{'tag': 'button', 'text': '折叠下方', 'left': 100, 'right': 200,
                              'top': 3000, 'bottom': 3030}])
    ok = check('回归守卫:长页面折叠线下的按钮不报 B',
               len([f for f in judge(longpage, '/synthetic-long', th, W) if f['axis'] == 'B']), 0,
               '实测自 /leave/approvals 的 9 个假红') and ok
    # 回归守卫 2/3：**完全在视口外**的不判（a11y skip-link 实测就是这个形状）
    skip1 = dict(synth, scroll_width=375, texts=[],
                 buttons=[{'tag': 'a', 'text': '跳至内容', 'left': -1, 'right': 0,
                           'top': -1, 'bottom': 35}])
    ok = check('回归守卫:a11y skip-link(left-1,right0) 不报 B',
               len([f for f in judge(skip1, '/synthetic-skip', th, W) if f['axis'] == 'B']), 0,
               '实测自 /my/password 的「跳至内容」') and ok
    skip2 = dict(synth, scroll_width=375, texts=[],
                 buttons=[{'tag': 'a', 'text': '藏件', 'left': -9999, 'right': -9879,
                           'top': 0, 'bottom': 30}])
    ok = check('回归守卫:left:-9999 的藏件不报 B',
               len([f for f in judge(skip2, '/synthetic-hidden', th, W) if f['axis'] == 'B']), 0) and ok
    # 真缺陷仍必须报：控件横向**部分**出界
    cut = dict(synth, scroll_width=375, texts=[],
               buttons=[{'tag': 'button', 'text': '批准', 'left': 300, 'right': 460,
                         'top': 100, 'bottom': 130}])
    ok = check('真缺陷:横向部分出界仍报 B',
               len([f for f in judge(cut, '/synthetic-cut', th, W) if f['axis'] == 'B']), 1) and ok
    print('  正样本（合成）命中轴 %s ｜ 正样本（真实 %s）命中轴 %s（仅供参考，不作断言）'
          % (sorted(s_axes), pos_path, sorted({f['axis'] for f in pos['findings']}) or '无'))
    ok = check('负样本:真实页一条都不报', len(neg['findings']), 0,
               'overflow=%dpx' % neg['viewport'][vp_key]['overflow_px']) and ok
    ok = check('负样本:真实页无横向溢出',
               neg['viewport'][vp_key]['overflow_px'] <= th['overflow_px'], True) and ok

    # 量具记账必须真的落进读数（否则「重启过几次」下次还是要靠猜）
    ok = check('engine:自证这一轮的 browser 重启数 = 0（只有 2 条探页）',
               engine.get('browser_restarts'), 0,
               'restart_every=%s，重启点 %s' % (engine.get('restart_every'),
                                                engine.get('restarted_before_probe'))) and ok
    doc = build_doc(readings, [], [], conc, th, {'started': started}, ctr, env_failed, engine)
    ok = check('engine:meta.probe_engine 落进读数',
               (doc['meta'].get('probe_engine') or {}).get('restart_every'),
               BROWSER_RESTART_EVERY) and ok
    doc['meta']['group'] = 'usability-selftest'
    doc['meta']['axes'] = '正样本 %s（须报红） vs 负样本 %s（须不报红）' % (pos_path, neg_path)
    p = write_readings(doc, tag='selftest')
    print('  -> 自证读数落盘：%s（指纹 %s）' % (p, doc['fingerprint']))

    SELFTEST_CASES = emitted
    print('')
    print('== 自证结论：%s（断言 %d 条；合成正样本命中轴 %s ｜ 真实负样本 %s ｜ '
          'browser 重启 %d 次/每 %d 条）=='
          % ('通过' if ok else '不通过', emitted,
             ''.join(sorted(s_axes)) or '无',
             '干净' if not neg['findings'] else '有命中',
             engine.get('browser_restarts', 0), BROWSER_RESTART_EVERY))
    print('自证行：%s' % self_attest_line())
    return 0 if ok else 1


# ---------------------------------------------------------------- 主流程
def print_list(rows, plan, skipped, thresholds):
    print('== 名单来源：%s（scope=portal）%d 条 ==' % (SURFACE, len(rows)))
    print('== 阈值：视口 %dx%d ｜ A 横向溢出 >%dpx ｜ B 横向越界（右/左出界 或 bottom<0）=='
          % (thresholds['vpx'], thresholds['vpy'], thresholds['overflow_px']))
    print('-- 可探 %d 条（身份 × 路径；每条单次 GET；同一路径最多 2 个身份）--' % len(plan))
    for it in plan:
        print('[PROBE] %-9s %-42s %s' % (it['role'], it['path'], it['src']))
    print('-- 排除 %d 条（红线 1：副作用守卫 / 无实例）--' % len(skipped))
    for s in skipped:
        print('[SKIP]  %-9s %-42s skipped(%s)' % (s['role'], s['path'], s['skipped']))
    print('== 退出码 0 = 名单读得到（--list 只打印，不判门禁）==')
    return 0


def run(mode, thresholds, log=print):
    rows, err = load_surface()
    if err:
        log('INCOMPLETE：%s %s' % (SURFACE, err))
        log('  名单没有来源 ⇒ 本轮不探、不判 FAIL（退出码 3）。登记表由 A 组维护。')
        log('  这里**不退回写死名单** —— 那等于把刚拆掉的第二份名单重新长出来。')
        return 3
    wording, werr = load_wording()
    if werr:
        log('INCOMPLETE：%s %s' % (WORDING, werr))
        return 3
    plan, skipped = build_plan(rows, load_instances())
    if mode == 'list':
        return print_list(rows, plan, skipped, thresholds)
    if not site_ready():
        log('ENV：站点不可达 %s（只读探本机栈；不重启服务）' % BASE)
        return 2
    log('== 名单 %s scope=portal：%d 条 -> 探页 %d 条（身份 × 路径）/ 排除 %d 条 =='
        % (SURFACE, len(rows), len(plan), len(skipped)))
    readings, failed, env_failed, dl_skipped, conc, started, ctr, engine = probe_all(
        plan, thresholds, wording)
    skipped = skipped + dl_skipped
    doc = build_doc(readings, skipped, failed, conc, thresholds,
                    {'started': started}, ctr, env_failed, engine)
    p = write_readings(doc)
    c = doc['meta']['counts']
    log('')
    log('================ 汇总 ================')
    log('探页 %d 条 = %d 页 × 身份；探到 %d ｜ 非环境失败 %d ｜ 环境失败 %d ｜ 排除 %d'
        % (len(plan), c['paths'], len(readings), len(failed), len(env_failed), len(skipped)))
    log('命中（原始）：A %d ｜ B %d ｜ C %d ｜ D %d = %d 条；去重键 %d 个（报红 %d 条 / %d 页）'
        % (doc['axes']['A'], doc['axes']['B'], doc['axes']['C'], doc['axes']['D'],
           sum(doc['axes'].values()), len(doc['findings']),
           c['red_probes'], c['red_paths']))
    log('读数落盘：%s（指纹 %s）' % (p, doc['fingerprint']))
    log('采集时刻 %s ｜ 并发 %s ｜ 容器 %s（StartedAt %s -> %s，样本有效=%s）'
        % (started, conc, ctr.get('name'), ctr.get('before'), ctr.get('after'),
           ctr.get('sample_valid')))
    # 量具记账（队长 2026-09-28 裁定）：重启 browser 是**重置量具**，不是重试；
    # 结论行必须自报重启次数，否则下次看到超时又要从头查一遍。
    log('探页引擎：browser 重启 %d 次（每 %d 条一次%s）｜ 探页异常（非环境）%d 条%s'
        % (engine.get('browser_restarts', 0), engine.get('restart_every', BROWSER_RESTART_EVERY),
           '，重启点 ' + str(engine.get('restarted_before_probe')) if engine.get('browser_restarts') else '',
           len(failed),
           '' if not failed else ' => 仍 INCOMPLETE(3)：%s' % [f['path'] for f in failed[:4]]))
    env_ret, env_note = env_verdict(env_failed, ctr)
    if env_note:
        log(env_note)

    if mode == 'report':
        print_findings(doc['findings'], '当前全部命中（--report：不与基线比对）')
        log('自证行：%s' % self_attest_line())
        return env_ret or (3 if failed else 0)

    if env_note:
        log('ENV：样本作废 => 本轮不冻结基线、不与基线比对（不看绿也不看红）')
        log('自证行：%s' % self_attest_line())
        return 2

    if mode == 'baseline':
        with open(repo_path(BASELINE_PATH), 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
        log('基线已冻结：%s（指纹 %s，采集时刻 %s）—— 存量问题记账，不阻断'
            % (BASELINE_PATH, doc['fingerprint'], started))
        log('自证行：%s' % self_attest_line())
        return 3 if failed else 0

    # mode == 'check'
    base, berr = load_baseline()
    if berr:
        log('INCOMPLETE：%s' % berr)
        log('  基线没有来源 ⇒ 不判绿（退出码 3）；这不是"通过"。')
        return 3
    if (base.get('meta') or {}).get('thresholds') != thresholds:
        log('⚠ 阈值与基线不同（基线 %s / 本轮 %s）⇒ 不可比，按 INCOMPLETE 处理'
            % ((base.get('meta') or {}).get('thresholds'), thresholds))
        return 3
    tol = thresholds.get('worsen_tolerance', 0)
    new, worse, gone = compare(doc['findings'], base.get('findings') or [], tolerance=tol)
    base_at = ((base.get('meta') or {}).get('collected_at') or {}).get('probe')
    log('')
    log('==== --check（ratchet：只报新增/恶化）====')
    log('基线指纹 %s ｜ 基线采集时刻 %s ｜ 本轮指纹 %s ｜ 本轮采集时刻 %s'
        % (base.get('fingerprint'), base_at, doc['fingerprint'], started))
    print_findings(new, '新增（基线里没有）')
    print_findings([w['cur'] for w in worse], '恶化（同键 metric 变大）')
    for w in worse:
        log('   ↑ %s：metric %s -> %s' % (w['cur']['key'], w['base']['metric'],
                                          w['cur']['metric']))
    log('-- 改善（INFO，不阻断）：%d 条 --' % len(gone))
    log('（恶化判定 = 同键 metric 超出容差 %dpx；共享栈数据抖动不会报警）' % tol)
    for it in gone:
        log('   ↓ %s' % it['key'])
    log('自证行：%s' % self_attest_line())
    if failed:
        log('INCOMPLETE：%d 页没探到 ⇒ 不判绿（退出码 3）' % len(failed))
        return 3
    if new or worse:
        log('结论：**有新增/恶化 -> 报警**（新增 %d / 恶化 %d）' % (len(new), len(worse)))
        return 1
    log('结论：无新增、无恶化（在基线内；改善 %d 条，可考虑重新冻结基线）' % len(gone))
    return 0


def main():
    # global 必须在**本函数内首次使用 BASE/DB 之前**声明（否则 SyntaxError：used prior to global）
    global BASE, DB, ROLE_LOGINS, STAFF_ROLES, ALL_ROLES
    ap = argparse.ArgumentParser(description='可用性门禁（四轴：溢出 / 主操作 / 措辞 / 空态出口）')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--selftest', action='store_true', help='只证量具（纯函数 + 真实页正负对照）')
    g.add_argument('--list', action='store_true', help='只读打印名单与排除账（不连站点）')
    g.add_argument('--report', action='store_true', help='全量现探 + 打印全部命中')
    g.add_argument('--baseline', action='store_true', help='冻结当前读数为基线')
    g.add_argument('--check', action='store_true', help='与基线比对（只报新增 / 恶化）')
    ap.add_argument('--overflow-px', type=int, default=OVERFLOW_PX, help='A 轴阈值（默认 8）')
    ap.add_argument('--button-bottom-factor', type=float, default=BUTTON_BOTTOM_FACTOR,
                    help='B 轴下边界倍数（默认 1.5）')
    ap.add_argument('--viewport', default='%dx%d' % (VIEWPORT_W, VIEWPORT_H),
                    help='视口 WxH（默认 375x812）')
    ap.add_argument('--worsen-tolerance', type=int, default=WORSEN_TOLERANCE,
                    help='ratchet 恶化容差 px（默认 8；共享栈数据抖动，见常量注释）')
    # ---- 2026-10-02 新增：让本门禁能指向**任意源站**，从而第一次覆盖生产 ----
    # 起因：BASE 原先硬编码 http://localhost:8069 ⇒ 这条门禁**从来没有在生产上跑过**，
    #   而生产才是学生/教务真正看到的界面（同类盲区已致一次事故：换机后生产缺 db_name，
    #   匿名页全绿、登录后全站 404，正是「只测本地」才漏掉的）。
    # 默认值与旧行为**逐字相同**，不加参数即等价于改造前。
    ap.add_argument('--base-url', default=BASE, help='被测源站（默认 %s）' % BASE)
    ap.add_argument('--db', default=DB, help='库名（默认 %s）' % DB)
    ap.add_argument('--users-file', default=None,
                    help='JSON：{"角色": ["登录名", "口令"]}，覆盖默认演示账号表（生产没有 stu@local 等演示号）')
    ap.add_argument('--all-roles', action='store_true',
                    help='每页探**全部**登记身份（默认只探 1–2 个）。用于「整页无死角」复检；'
                         '读数与默认模式不同源，不可直接与基线比大小')
    ap.add_argument('--roles', default=None,
                    help='只探这些身份（逗号分隔）。用于目标环境缺少某些账号时如实缩小覆盖面，而不是拿错账号冒充')
    args = ap.parse_args()
    w, h = (int(x) for x in args.viewport.lower().split('x'))
    thresholds = {'vpx': w, 'vpy': h, 'overflow_px': args.overflow_px,
                  'button_bottom_factor': args.button_bottom_factor,
                  'worsen_tolerance': args.worsen_tolerance}
    if args.selftest:
        return selftest()
    # ---- 目标环境覆盖（默认不动）----
    ALL_ROLES = bool(args.all_roles)
    if ALL_ROLES:
        print('[cfg] --all-roles：每页探全部登记身份（默认只探 1–2 个）')
    BASE = args.base_url.rstrip('/')
    DB = args.db
    if args.users_file:
        with open(args.users_file, encoding='utf-8') as fh:
            ROLE_LOGINS = json.load(fh)
        print('[cfg] 账号表来自 %s：%s' % (args.users_file, ','.join(sorted(ROLE_LOGINS))))
    if args.roles:
        want = [r.strip() for r in args.roles.split(',') if r.strip()]
        missing = [r for r in want if r not in ROLE_LOGINS]
        if missing:
            print('[cfg] ⛔ 这些身份没有可用账号，拒绝用别的账号冒充：%s' % ','.join(missing))
            return 2
        ROLE_LOGINS = {r: ROLE_LOGINS[r] for r in want}
        STAFF_ROLES = tuple(r for r in STAFF_ROLES if r in ROLE_LOGINS)
        print('[cfg] 只探身份：%s（其余身份本轮**未覆盖**，读数里不含它们）' % ','.join(want))
    print('[cfg] 目标 = %s ｜ 库 = %s' % (BASE, DB))
    mode = ('list' if args.list else 'baseline' if args.baseline
            else 'check' if args.check else 'report')
    return run(mode, thresholds)


if __name__ == '__main__':
    sys.exit(main())
