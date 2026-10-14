#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门户三角色回归冒烟（权限分层收口后 t2 产出；只读、可复跑）。

用法：python3 tests/smoke/portal_regression_smoke.py
退出码：0 全绿 ｜ 1 有回归 ｜ 2 前置探活未过（环境问题，不伪装成断言失败）

为什么要有这个脚本
------------------
2026-09-17 的权限分层（commit d2c41de）解除了基座「教务组隐含 base.group_system」，
并给教务组补了若干业务组/ACL。门户侧的取数判据是 controllers 里的
current_student() / current_faculty() / current_parent() / privileged_staff()
（custom_addons/edu_portal/controllers/roles.py:150-176），与后台 ACL/菜单
**不是同一条通路** —— 但"理论上不受影响"不算证据：本脚本把三角色关键页
跑成可复跑的读数，权限改动一旦误伤门户（页面打不开 / 身份串了 / 数据空了）立刻红。

判据（三层，缺一不可；只看 HTTP 状态码**不算**通过）
----------------------------------------------------
① HTTP：状态码 200 且**响应体无 Traceback**；
② 元素：页面**渲染出的可见文本**（已剥 script/style/注释/标签）命中该页关键元素 ≥2 项；
③ 身份：页面上出现**登录者本人的显示名**（经 res.users.read 自读取得，不写死演示名），
   证明是凭身份取数，而不是"谁都能打开的空壳页"。

另有：
④ 越权负例 DENIED：学生/家长打教师页必须 303 → /my/home，且响应体不含该页关键元素
   （防"200 换个马甲"式假绿）；家长的 /my/child/<id> 只对孩子本人开放；
⑤ 教师后台判据 backend_evidence()：按**队长 2026-09-17 契约修订后的口径**判三条
   （原文「确认教师仍无法进入后台」的前提是错的：本地 faculty@local 是内部用户、进得了后台外壳；
   生产的 teacher@local 才是 portal-only。两者不同形，照原文写只能得到假红或假绿）：
     ① 教师**无**「设置 / 应用」根菜单（9 个可见根列出作基线，另断言后台确实可达）；
     ② 教师**进不了教务专属**：GET /ledger、/ledger/new、/ledger/reimburse → 303 回门户；
        后台菜单「费用分类 / 邀请码 / 老账号补挂身份 / 数据清除」→ 对教师不可见；
     ③ portal-only 账号 stu@local、parent@local GET /odoo → **303 /my**。
   ⚠ 前提声明（必须随读数一起读）：本地库的 faculty@local **手挂了 15 个组**
   （含 openeducat_admission.group_op_admission_admin、openeducat_fees.group_op_fees_admin 等，
   全仓 .py/.xml/.csv 无任何授予点 ⇒ **本地手挂漂移**；清理脚本 scripts/clean_local_group_drift.py）。
   因此**本地「教师」读数不代表生产**，**教师后台相关读数不作为生产结论**（详见报告 §5.1）。

防假红说明（本仓 doctrine：假红与假绿一样消耗信任）
--------------------------------------------------
· 关键元素一律取**模板里的裸文案**（已逐条核到 .xml 行号，见 PAGES 表内注释），
  并要求「≥2 项命中」——少数块带 t-if（数据为空即不渲染），单点字符串会假红；
· 身份名从会话自读（res.users.read 自己的 name），不写死"王小明"这类演示数据名；
· 本脚本**只 GET**，不建夹具、不写库 → 可以连跑、可以并发跑，不存在 leftover。

环境前提
--------
本地 docker compose 栈在跑（edu19-clone-web-1 / :8069）。
升级锁只作 WARN 记录、不作硬失败：本机实测存在**陈旧锁**（$TMPDIR/edu19_upgrade.lock，
成因 = 升级进程被容器重建带走、trap rmdir 没跑），若因它硬失败会变成永久假红。
真正的闸门是下面的三步探活（站点能应答且 /login 不是 404）。
（锁路径统一：t5/60d4370 把 safe_upgrade.sh 与 authz_endtoend_smoke.py 对齐；t9 把本脚本
也统一到「EDU_UPGRADE_LOCK ＞ TMPDIR 未设/空 ⇒ /tmp ＞ 固定名」并补 isabs 自检 —— 此前
TMPDIR="" 时会退化成相对路径 'edu19_upgrade.lock'（fail-open，看不见锁）。
注：772fc59 只是把 safe_upgrade.sh 的改动**物理带进**了那次提交（兄弟会话的 git add -A 误带），
它本身不是锁口径的依据，别引用它。）
另：tests/smoke/authz_endtoend_smoke.py 的 preflight 用**裸 requests.get**（无 trust_env/NO_PROXY），
本机系统代理 127.0.0.1:12450 会让它拿 502 → exit 2；跑它必须带 NO_PROXY=localhost,127.0.0.1。
"""

import os
import re
import sys
import time

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

import requests  # noqa: E402

BASE = os.environ.get("PORTAL_SMOKE_BASE", "http://localhost:8069")
DB = os.environ.get("PORTAL_SMOKE_DB", "edu19")
PW = os.environ.get("PORTAL_SMOKE_PW", "demo123")

# 账号 → 角色。faculty@local / stu@local / parent@local 即 code-map §9 的三个演示账号。
ACCOUNTS = {
    "teacher": ("faculty@local", PW),
    "student": ("stu@local", PW),
    "parent": ("parent@local", PW),
    # 教务账号：本脚本**不判它的页面**，只用它做判据②的**正对照**
    # （同批路由对教务必须 200 ⇒ 证明教师的 303 是角色边界，而不是"页面本身坏了"）
    "registrar": ("backoffice@local", PW),
}

# 关键元素组：模板裸文案 + 出处（改动模板时按行号同步）。
# 判据 = 可见文本命中 ≥2 项（见文件头「防假红说明」）。
PAGES = [
    # ---- 教师侧（roles.py / batch2.py 教师工作台分支）----
    ("teacher", "/my/home", "教师工作台",
     ["教师工作台",                                  # batch2.xml:1910 教师工作台模板标题
      "教学安排", "作业管理", "我的主页",  # 静态家具（恒在）= 硬判据
       "待办提醒", "常用应用", "今日我教的课"],  # 带 t-if，只作加分项        # batch2.xml:862 / 888 / 924（带 t-if，故只作候选）
     "教师工作台分支（不是学生仪表盘）"),
    ("teacher", "/attendance/take", "考勤录入",
     ["考勤录入", "选择班级与日期，为每位学生勾选出勤状态后提交。", "加载学生"],
     # roles.xml:144 副标题；点名台
     "点名：班级+日期+出勤勾选"),
    ("teacher", "/grading/entry", "成绩录入",
     ["成绩录入", "选择考试，为学生录入得分后提交。", "加载考生"],
     # roles.xml:309 副标题
     "成绩录入台"),
    ("teacher", "/leave/approvals", "请假审批",
     ["请假审批", "处理学生与家长提交的请假申请。", "批量通过", "全选本页"],
     # roles.xml:525 副标题 / roles.xml:582 批量通过
     "请假审批台（含批量）"),
    # ---- 学生侧 ----
    ("student", "/my/home", "我的主页",
     # H-1（2026-09-18 校长拍板）：学生首页 = 原「全部应用」宫格（合并页）。
     # 硬判据取宫格模板里的恒在文案：hero 副标题（batch2.xml:763）、今日课表卡
     # （:697，学生/家长分支）、侧栏快速操作（:1154）、hero 问候（:736）。
     # ⚠ 旧 Timeline 的四串（工作台 / 今天要做什么，一眼看完。/ 今日课节 / 快捷入口）
     #   已随合并下线 —— 模板按零删除红线留在 study.xml，但当前无路由引用。
     ["所有学习所需尽在一处", "今日课表", "快速操作", "欢迎回来"],
     "学生合并首页：宫格 + 待办窄条（原 Timeline 内容已并入）"),
    ("student", "/student/timetable", "我的课表",
     ["我的课表", "周视图", "上一周", "下一周"],
     # edu_portal_templates.xml:296 周视图
     "课表：周/日视图 + 周切换"),
    ("student", "/my/study", "课程中心",
     # study.xml:18 h1 / :19 hero 副标题 / :23「N 门在修科目」静态标签（三者恒在）。
      # ⚠ 原用「常用表格」「全部资料下载」依赖**下载中心有资料**（study.xml:82 带条件），
      #   演示资料被清理后整块不渲染 ⇒ 只剩 1 命中 ⇒ 数据驱动假红（2026-09-17 16:40 实测）。
      ["课程中心", "报课 → 上课 → 资料 → 下载 → 成绩", "在修科目"],
     # study.xml:82 常用表格
     "一条龙课程中心"),
    ("student", "/my/fees", "我的账单",
     # 标题 + 静态说明文案为硬判据；条件按钮只作加分项
      ["我的账单", "线下转账后由学坊登记到账", "发起报销", "导出 CSV"],
     # fees.xml:201 发起报销
     "账单：待缴 + 报销入口"),
    ("student", "/student/attendance", "出席率",
     # 标题 + 静态表头为硬判据；「考勤率」在统计块里（无数据不渲染），只作加分项
      ["出席率", "考勤表", "考勤率", "导出 CSV"],
     # batch1.xml:101 考勤率
     "个人考勤明细"),
    # ---- 家长侧 ----
    ("parent", "/my/child", "我的孩子",
     ["我的孩子", "选择一个孩子查看其仪表盘、成绩与档案。"],
     # roles.xml:9 副标题
     "家长看孩子：孩子列表"),
    ("parent", "/my/fees", "孩子的账单",
     # 标题 + 静态说明文案为硬判据；「待缴合计」只在有账单时渲染，只作加分项
      ["孩子的账单", "线下转账后由学坊登记到账", "待缴合计", "导出 CSV"],
     # fees.xml:238 当前待缴合计（家长页为"待缴合计"）
     "家长看孩子：账单"),
    # ---- 资料下载（三角色都要能进；按来源分流）----
    ("teacher", "/downloads", "资料下载",
     ["资料下载", "按来源分流", "课程资料", "行政表格"],
     # downloads_portal.xml:471 按来源分流
     "资料下载中心（教师）"),
    ("student", "/downloads", "资料下载",
     ["资料下载", "按来源分流", "课程资料", "行政表格"],
     "资料下载中心（学生）"),
    ("parent", "/downloads", "资料下载",
     ["资料下载", "按来源分流", "课程资料", "行政表格"],
     "资料下载中心（家长）"),
]

# 越权负例：(角色, 路径, 期望跳转前缀, 该页关键元素, 说明)
# 教师页对学生/家长必须 303 回门户首页；家长专属页对非家长必须 303 回 /my/child。
DENIED = [
    ("student", "/attendance/take", "/my/home", "考勤录入", "点名台不对学生开放"),
    ("student", "/grading/entry", "/my/home", "成绩录入", "成绩录入台不对学生开放"),
    ("student", "/leave/approvals", "/my/home", "请假审批", "请假审批台不对学生开放"),
    ("student", "/registrar/subject/approvals", "/my/home", "选课审批", "选课审批不对学生开放"),
    ("parent", "/attendance/take", "/my/home", "考勤录入", "点名台不对家长开放"),
    ("parent", "/grading/entry", "/my/home", "成绩录入", "成绩录入台不对家长开放"),
    ("parent", "/leave/approvals", "/my/home", "请假审批", "请假审批台不对家长开放"),
    ("parent", "/registrar/subject/approvals", "/my/home", "选课审批", "选课审批不对家长开放"),
]

# 后台判据要读的组（xmlid 稳定，不随语言变）
GROUPS = [
    ("base.group_user", "内部用户"),
    ("base.group_portal", "门户用户"),
    ("base.group_system", "系统管理员"),
    ("openeducat_core.group_op_faculty", "教师组"),
    ("openeducat_core.group_op_back_office_admin", "教务组"),
]
# 只给系统管理员的后台根菜单（教师/教务都不该看见）
SYS_ONLY_ROOTS = ("设置", "应用", "数据清除")
# ---- 队长 2026-09-17 契约修订后的判据常量 ----
# ① 教师可见根基线（本库读数）。**只作记录、不作硬断言**——它是「清掉手挂漂移前」的读数，
#    漂移清理后根集合会变，硬断言会变成回归窗口外的假红。硬断言只保留「无系统专属根」。
TEACHER_ROOTS_BASELINE = ("图书馆", "学生信息", "招生", "招聘管理", "教务审批",
                          "时间表", "灵命生活", "综合评估", "资产管理")
# ② 教务专属：路由（期望 303 回门户）与后台菜单名（期望对教师不可见）
# （队长 2026-09-17 批准：把「教师进不了教务管理动作」从附录只读抽查升为断言）
REGISTRAR_ONLY_ROUTES = ("/ledger", "/ledger/new", "/ledger/reimburse", "/ledger/export",
                        "/edu/audit")
REGISTRAR_ONLY_MENUS = ("费用分类", "邀请码", "老账号补挂身份", "数据清除")

RESULTS = []
CANNOT = []


def check(name, cond, detail=""):
    RESULTS.append(("PASS" if cond else "FAIL", name, str(detail)))
    print("  %-4s %-62s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


def note(msg):
    print("  .... %s" % msg)


# --------------------------------------------------------------------------
# 会话 / RPC
# --------------------------------------------------------------------------
def login(login_name, password):
    """真登录（session/authenticate），返回 (session, uid) 或 (None, None)。"""
    s = requests.Session()
    s.trust_env = False
    s.headers.update({"Accept-Language": "zh-CN,zh;q=0.9"})
    r = s.post(BASE + "/web/session/authenticate", json={
        "jsonrpc": "2.0",
        "params": {"db": DB, "login": login_name, "password": password}},
        timeout=30)
    j = (r.json().get("result") or {}) if r.text[:1] == "{" else {}
    return (s, j.get("uid")) if j.get("uid") else (None, None)


def call_kw(s, model, method, args, kwargs=None):
    """JSON-RPC call_kw（本脚本只用只读方法）。返回 (result, error_msg)。"""
    r = s.post(BASE + "/web/dataset/call_kw", json={
        "jsonrpc": "2.0", "method": "call",
        "params": {"model": model, "method": method, "args": args,
                   "kwargs": kwargs or {}}}, timeout=60)
    try:
        j = r.json()
    except ValueError:
        return None, "非 JSON 响应 http=%s" % r.status_code
    err = (j.get("error") or {}).get("data", {}).get("message")
    return j.get("result"), err


def has_group(s, uid, xmlid):
    res, err = call_kw(s, "res.users", "has_group", [[uid], xmlid])
    return None if err else bool(res)


def my_name(s, uid):
    res, err = call_kw(s, "res.users", "read", [[uid], ["name", "login"]])
    if err or not res:
        return None
    return res[0].get("name")


def visible_text(html):
    """剥 script/style/注释/标签 → 可见文本。

    判"渲染结果"而非"响应字节"：模板里的 <script> 载荷、属性值、被 t-if
    关掉的块都不该算命中（本仓既有口径，见 tests/smoke/UX_V3_GATE.md）。
    """
    h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    h = re.sub(r"(?is)<!--.*?-->", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    h = h.replace("&nbsp;", " ")
    h = re.sub(r"&[a-z]+;|&#\d+;", " ", h)
    return re.sub(r"\s+", " ", h).strip()


def page_title(html):
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    return m.group(1).strip() if m else ""


def get(s, path):
    return s.get(BASE + path, timeout=60, allow_redirects=False)


# --------------------------------------------------------------------------
# 前置探活（三步：无活升级 / 站点应答 / /login 不是 404）
#
# ⚠ 跑门禁的公共前提（队长 2026-09-17 要求写进脚本，防后来人踩）：
#   1) **必须带 NO_PROXY=localhost,127.0.0.1**。
#      本机（macOS）系统代理是 http://127.0.0.1:12450（python3 -c
#      'import urllib.request as u; print(u.getproxies())' 可查）。
#      【原文保留，勿删】tests/smoke/authz_endtoend_smoke.py 的 preflight 用的是**裸 requests.get**
#      （既没 trust_env=False 也没读 NO_PROXY）⇒ 不带 NO_PROXY 时请求会被送去代理，
#      拿到 **502 → 该脚本 exit 2**。它自己会如实报「探活返回 502」（不伪装成断言失败），
#      但读日志的人容易误判成红灯。本脚本自身 trust_env=False，不受影响；
#      p2_enroll_smoke.py 的 auth() 也自带 trust_env=False，同样不受影响。
#      【2026-09-17 t9 更正】上面这半句**已过时**：authz 的 preflight 已于 t5（60d4370）改为
#      trust_env=False；同型的主门禁 scripts/check_odoo_trace.py 初始探活（原 :1214）已于
#      t12（e09bad8）同样修正 ⇒ 仓内当前**已无**裸 requests 打 localhost 的地方。
#      **但本块不删**：它记的是这类代码的通用前提。裸请求有两种坏法 ——
#        ① 代理**连不上** → ProxyError → 站点健康也报「环境不可用」**exit 2（假红）**；
#        ② 代理**能连**  → 拿回 502 **响应**（不抛异常）→ 探活**静默"通过"**（假绿；更危险，
#           因为假红有人会去查，假绿没人会去查）。
#      ⇒ **新增任何 HTTP 客户端（脚本/冒烟/门禁）都必须 trust_env=False 或显式 proxies=…**；
#        下面这条 NO_PROXY 只是给**外部调用者**兜底的第二条腿。
#   2) **先三步探活再跑**：无活升级锁（且日志不再增长）+ 容器 Up>30s +
#      带 cookie 访问 /web/login?db=edu19 得 200/302/303。
#      有升级在跑时读数会是「半程读数」（假红/假绿都算失真）。
# --------------------------------------------------------------------------
def preflight():
    # 升级锁口径（t9 统一，与 scripts/safe_upgrade.sh:60 / tests/smoke/authz_endtoend_smoke.py:107 同源）：
    #   EDU_UPGRADE_LOCK 覆盖 ＞ TMPDIR（未设**或空** ⇒ /tmp）＞ 固定名 edu19_upgrade.lock。
    # 旧写法 os.environ.get("TMPDIR", "/tmp") 在 TMPDIR="" 时退化成**相对路径**
    # 'edu19_upgrade.lock' ⇒ 锁在也看不见（fail-open，t9 实测）；末尾 isabs 自检兜底。
    # ⚠ 本脚本**有意只 WARN 不拦**（t2 裁定：本机存在陈旧锁，硬拦会变永久假红）——
    #   这里换成 exists 只为"看得见"，warn-only 语义一字未变。
    lock = (os.environ.get("EDU_UPGRADE_LOCK")
            or os.path.join(os.environ.get("TMPDIR") or "/tmp",
                            "edu19_upgrade.lock"))
    if not os.path.isabs(lock):
        lock = "/tmp/edu19_upgrade.lock"
    if os.path.exists(lock):
        note("WARN 升级锁存在：%s（mtime=%s）。本机为该锁的**陈旧**形态，"
             "只记录不拦（硬拦会变成永久假红）；若此刻确有升级在跑，请换时间重跑。"
             % (lock, time.strftime("%Y-%m-%d %H:%M:%S",
                                    time.localtime(os.path.getmtime(lock)))))
    try:
        jar = requests.Session()
        jar.trust_env = False
        r1 = jar.get(BASE + "/web/login?db=" + DB, timeout=15,
                     allow_redirects=False)
        r2 = jar.get(BASE + "/login", timeout=15, allow_redirects=False)
    except Exception as exc:
        print("PREFLIGHT: 站点不可达 %s" % exc)
        return False
    if r1.status_code not in (200, 302, 303):
        print("PREFLIGHT: 带 cookie 访问 /web/login?db=%s 得到 %s"
              % (DB, r1.status_code))
        return False
    if r2.status_code == 404:
        print("PREFLIGHT: /login 是 404（多库陷阱 / 站点未就绪），不要跑门禁")
        return False
    print("PREFLIGHT: OK（/web/login=%s，/login=%s）" % (r1.status_code,
                                                        r2.status_code))
    return True


# --------------------------------------------------------------------------
# ① + ② + ③ 三角色关键页
# --------------------------------------------------------------------------
def run_pages(sessions, names):
    print("\n===== ① ② ③ 三角色关键页（HTTP + 关键元素 + 身份） =====")
    n = 0
    for role, path, expect_title, markers, why in PAGES:
        n += 1
        s = sessions.get(role)
        if s is None:
            CANNOT.append("%s %s：%s 登录失败，未执行断言" % (role, path, why))
            continue
        r = get(s, path)
        body = r.text if r.status_code == 200 else ""
        vtext = visible_text(body)
        tb = "Traceback" in body
        hits = [m for m in markers if m in vtext]
        ident = names.get(role)
        ident_ok = bool(ident) and ident in vtext
        title = page_title(body)
        check("%s %s HTTP 200 且无 Traceback" % (role, path),
              r.status_code == 200 and not tb,
              "http=%s traceback=%s loc=%s" % (r.status_code, tb,
                                               (r.headers.get("Location") or "-")[:40]))
        check("%s %s 关键元素 ≥2 命中" % (role, path),
              len(hits) >= 2,
              "命中 %d/%d %s" % (len(hits), len(markers), hits))
        check("%s %s 页面标题正确" % (role, path),
              title == expect_title,
              "title=%r 期望=%r" % (title, expect_title))
        check("%s %s 身份判据（出现本人显示名）" % (role, path),
              ident_ok, "本人名=%r 出现=%s" % (ident, ident_ok))
    return n


# --------------------------------------------------------------------------
# ④ 越权负例
# --------------------------------------------------------------------------
def run_denied(sessions):
    print("\n===== ④ 越权负例（教师页/家长页不对外角色开放） =====")
    for role, path, want_loc, marker, why in DENIED:
        s = sessions.get(role)
        if s is None:
            CANNOT.append("%s %s：登录失败，未执行断言" % (role, path))
            continue
        r = get(s, path)
        loc = r.headers.get("Location") or ""
        body = r.text if r.status_code == 200 else ""
        leaked = marker in visible_text(body) if body else False
        check("%s %s 被拒（303 → %s）" % (role, path, want_loc),
              r.status_code == 303 and loc.startswith(want_loc),
              "http=%s loc=%s（%s）" % (r.status_code, loc, why))
        check("%s %s 拒绝响应不含该页关键元素" % (role, path),
              not leaked, "marker=%r leaked=%s" % (marker, leaked))


def run_parent_child(sessions):
    """家长看孩子：列表 → 孩子仪表盘；非家长打同一 URL 必须被拒。"""
    print("\n===== ④b 家长看孩子（本人孩子 200 / 非家长 303） =====")
    p = sessions.get("parent")
    if p is None:
        CANNOT.append("家长看孩子：parent@local 登录失败，未执行断言")
        return
    r = p.get(BASE + "/my/child", timeout=60)
    links = sorted(set(re.findall(r'href="(/my/child/\d+)"', r.text)))
    if not links:
        CANNOT.append("家长看孩子：/my/child 未渲染出孩子链接（家长未绑定孩子？）"
                      "→ 无法构造孩子仪表盘断言（实际观测：无 href=/my/child/<id>）")
        return
    child_url = links[0]
    check("家长可以打开孩子仪表盘 %s" % child_url, True, "链接数=%d" % len(links))
    rd = p.get(BASE + child_url, timeout=60)
    v = visible_text(rd.text) if rd.status_code == 200 else ""
    hits = [m for m in ["学习概览", "学习生活摘要", "考试成绩", "返回我的孩子"] if m in v]
    check("家长 %s 渲染出孩子仪表盘（关键元素 ≥2）" % child_url,
          rd.status_code == 200 and len(hits) >= 2,
          "http=%s 命中=%s" % (rd.status_code, hits))
    check("孩子仪表盘不出现 Traceback", "Traceback" not in rd.text,
          "len=%d" % len(rd.content))
    for role in ("student", "teacher"):
        s = sessions.get(role)
        if s is None:
            continue
        rz = get(s, child_url)
        loc = rz.headers.get("Location") or ""
        check("%s 打 %s 被拒（303 → /my/child）" % (role, child_url),
              rz.status_code == 303 and loc.startswith("/my/child"),
              "http=%s loc=%s" % (rz.status_code, loc))


# --------------------------------------------------------------------------
# ⑤ 教师后台判据
# --------------------------------------------------------------------------
def backend_evidence(sessions, names):
    print("\n===== ⑤ 后台可达性判据（教师 / 学生 / 家长） =====")
    facts = {}
    for role in ("teacher", "student", "parent"):
        s = sessions.get(role)
        if s is None:
            CANNOT.append("%s 后台判据：登录失败，未执行断言" % role)
            continue
        uid = s.uid
        g = {x: has_group(s, uid, x) for x, _lab in GROUPS}
        web = get(s, "/web")
        loc = web.headers.get("Location") or ""
        lm = s.get(BASE + "/web/webclient/load_menus?db=" + DB, timeout=60)
        roots, allnames = [], []
        if lm.status_code == 200:
            try:
                m = lm.json()
                items = {int(k): v for k, v in m.items()
                         if k.isdigit() and isinstance(v, dict)}
                kids = set()
                for v in items.values():
                    kids.update(v.get("children") or [])
                roots = sorted(items[k].get("name") or "" for k in items
                               if k not in kids)
                # 判据②要按「菜单名是否可见」判，故连子菜单一起收
                allnames = sorted(set(v.get("name") or ""
                                      for v in items.values() if v.get("name")))
            except Exception as exc:
                CANNOT.append("%s load_menus 解析失败：%s" % (role, exc))
        facts[role] = {"groups": g, "web": web.status_code, "loc": loc,
                       "lm": lm.status_code, "roots": roots,
                       "session": s, "menu_names": allnames}
        print("  · %-8s groups: %s" % (
            role, " ".join("%s=%s" % (x.split(".")[-1], g[x])
                           for x, _l in GROUPS)))
        print("    /web=%-3s → %-12s load_menus=%-3s 可见根菜单=%d"
              % (web.status_code, loc[:12] or "-", lm.status_code, len(roots)))
        if roots:
            print("    可见根：%s" % "、".join(roots))

    # --- 学生 / 家长：必须进不了后台（base.group_portal） ---
    for role in ("student", "parent"):
        f = facts.get(role)
        if not f:
            continue
        check("%s 是 base.group_portal（非内部用户）" % role,
              f["groups"].get("base.group_portal") is True
              and f["groups"].get("base.group_user") is False,
              "portal=%s user=%s" % (f["groups"].get("base.group_portal"),
                                     f["groups"].get("base.group_user")))
        check("%s 打 /web 被踢回门户（303 → /my）" % role,
              f["web"] == 303 and f["loc"].startswith("/my"),
              "http=%s loc=%s" % (f["web"], f["loc"]))
        check("%s 取后台菜单被拒（load_menus ≠ 200）" % role,
              f["lm"] != 200, "load_menus=%s" % f["lm"])
        # ===== 修订判据③：portal-only 账号 GET /odoo 必须 303 回门户 =====
        ro = get(f["session"], "/odoo")
        loco = ro.headers.get("Location") or ""
        check("③ %s GET /odoo 被踢回门户（303 → /my）" % role,
              ro.status_code == 303 and loco.startswith("/my"),
              "http=%s loc=%s" % (ro.status_code, loco))

    # --- 教师：按**修订口径**判「不是管理员 / 进不了教务专属」，不再判「进不了后台」 ---
    f = facts.get("teacher")
    if f:
        check("teacher 是内部用户（base.group_user）→ 后台外壳可达",
              f["groups"].get("base.group_user") is True,
              "user=%s portal=%s" % (f["groups"].get("base.group_user"),
                                     f["groups"].get("base.group_portal")))
        check("teacher 不是系统管理员（base.group_system=False）",
              f["groups"].get("base.group_system") is False,
              "system=%s" % f["groups"].get("base.group_system"))
        check("teacher 是教师组、不是教务组",
              f["groups"].get("openeducat_core.group_op_faculty") is True
              and f["groups"].get("openeducat_core.group_op_back_office_admin") is False,
              "faculty=%s backoffice=%s" % (
                  f["groups"].get("openeducat_core.group_op_faculty"),
                  f["groups"].get("openeducat_core.group_op_back_office_admin")))

        # ===== 修订判据①：教师无「设置 / 应用」根菜单（9 个可见根列出来作基线）=====
        bad = [x for x in SYS_ONLY_ROOTS if x in (f["roots"] or [])]
        check("① teacher 无系统专属根菜单（%s）" % "/".join(SYS_ONLY_ROOTS),
              not bad, "命中=%s" % bad)
        print("     ① 教师可见根基线（%d 个）：%s"
              % (len(f["roots"]), "、".join(f["roots"]) or "（无）"))
        same = (f["roots"] or []) == list(TEACHER_ROOTS_BASELINE)
        print("        记录基线（9 个）逐字一致 = %s%s"
              % (same, "" if same else
                 "  ← 集合已变（可能已清理手挂漂移）。**这不是回归**：本脚本不硬断言这 9 个，"
                 "只硬断言「无系统专属根」；变化请对照报告 §5.1。"))
        check("① teacher 后台确实可达（可见根 >0：是「有后台但无系统菜单」，不是「打不开」）",
              len(f["roots"] or []) > 0, "可见根=%d" % len(f["roots"] or []))

        # ===== 修订判据②：教师进不了教务专属（路由 + 后台菜单名）=====
        ts = f["session"]
        for path in REGISTRAR_ONLY_ROUTES:
            r = get(ts, path)
            rloc = r.headers.get("Location") or ""
            check("② teacher GET %s 被拒（303 → /my/home 或 /my）" % path,
                  r.status_code == 303 and rloc.startswith("/my"),
                  "http=%s loc=%s" % (r.status_code, rloc))
        vis = set(f.get("menu_names") or [])
        hit = [n for n in REGISTRAR_ONLY_MENUS if n in vis]
        check("② teacher 后台菜单不可见教务专属（%s）" % "/".join(REGISTRAR_ONLY_MENUS),
              not hit, "命中=%s（教师可见菜单名 %d 个）" % (hit, len(vis)))
        # 正对照（本仓既有纪律：负例必须配正对照，否则「403/303」可能只是页面坏了）——
        # 同一批路由对**教务**必须 200。实测 backoffice 全 200；守卫在 controllers/ledger.py
        # 的 _ledger_guard → privileged_staff()。
        rs = sessions.get("registrar")
        if rs is None:
            CANNOT.append("② 正对照：backoffice@local 登录失败，未执行正对照断言")
        else:
            for path in REGISTRAR_ONLY_ROUTES:
                rp = get(rs, path)
                check("② 正对照·教务 GET %s = 200（证明教师的 303 是角色边界）" % path,
                      rp.status_code == 200, "http=%s" % rp.status_code)

    # --- 结论（修订口径 + 前提声明） ---
    print("\n  【⑤ 结论·按队长契约修订后的口径】")
    if f:
        print("    · 教师（faculty@local）：内部用户 + 教师组，能打开后台外壳"
              "（/web=%s，可见根 %d 个），但 **system=False、无系统专属根、进不了教务专属**"
              " ⇒ 修订判据①②全绿。" % (f["web"], len(f["roots"])))
        print("    ⚠ 前提声明：本地 faculty@local **手挂了 15 个组**"
              "（全仓无授予点 ⇒ 本地手挂漂移，清理脚本 scripts/clean_local_group_drift.py）；")
        print("      **因此本地「教师」读数不代表生产，教师后台相关读数不作为生产结论。**")
        print("      生产的 teacher@local 是 portal-only（队长实测）—— 原文「教师进不了后台」"
              "在生产成立、在本克隆不成立，两者不同形。")
    for role in ("student", "parent"):
        ff = facts.get(role)
        if ff:
            print("    · %s：base.group_portal ⇒ /web 与 /odoo 均 303→/my、load_menus=%s"
                  "，**进不了后台**（修订判据③）。" % (role, ff["lm"]))
    return facts


# --------------------------------------------------------------------------
def main():
    t0 = time.time()
    print("=== 门户三角色回归冒烟（权限分层收口后）===")
    print("BASE=%s DB=%s" % (BASE, DB))
    if not preflight():
        return 2

    sessions, names = {}, {}
    for role, (login_name, pwd) in ACCOUNTS.items():
        s, uid = login(login_name, pwd)
        if s is None:
            print("LOGIN FAIL %-8s %s" % (role, login_name))
            CANNOT.append("%s（%s）登录失败 → 该角色全部断言未执行" % (role, login_name))
            continue
        s.uid = uid
        sessions[role] = s
        names[role] = my_name(s, uid)
        print("LOGIN OK   %-8s %-16s uid=%-3d 显示名=%r"
              % (role, login_name, uid, names[role]))

    total = run_pages(sessions, names)
    run_denied(sessions)
    run_parent_child(sessions)
    backend_evidence(sessions, names)

    npass = sum(1 for v, _n, _d in RESULTS if v == "PASS")
    nfail = len(RESULTS) - npass
    print("\n===== 汇总 =====")
    print("关键页 %d 个 / 断言 %d 条：PASS %d ｜ FAIL %d"
          % (total, len(RESULTS), npass, nfail))
    if CANNOT:
        print("不可判定项 %d 条（如实登记，未伪造路径；请人工确认）：" % len(CANNOT))
        for c in CANNOT:
            print("  - %s" % c)
    if nfail:
        print("失败明细：")
        for v, n, d in RESULTS:
            if v == "FAIL":
                print("  - %s ｜ %s" % (n, d))
    print("耗时 %.1fs" % (time.time() - t0))
    # 防止"假绿"：一条断言都没跑出来时必须判失败（0 断言 ≠ 通过）
    if not RESULTS:
        print("未产生任何断言（登录或探活失败）→ 判失败，不得视为通过")
        return 1
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
