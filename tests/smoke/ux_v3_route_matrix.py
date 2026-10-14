#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v3 门禁：路由 × 角色矩阵（≥60 路由 × 四角色 + admin）。

判定（每条 路由×角色）：
  * 硬失败 FAIL：任一跳出现 5xx、响应体含 Traceback / Internal Server Error、
    或该路由声明「本角色必须 200」而实际没拿到 200、或最终落地 4xx/5xx（404 例外见下）
  * PENDING：v3 待交付路由（/login、/apps、/my/apps、/my/study）当前 404 —— 如实列出，不计 FAIL
  * WARN：非预期 404（路由对别人存在、对本角色 404）、被弹回登录页、403
  * PASS：拿到 200（含 3xx 跳转后 200）

名单来源（B 组 2026-09-26 切换）：**tests/ui/surface.json**（登记表，A 组维护）里
gates 含 route_matrix 的条目 —— 本门禁**不再自带名单**（旧的写死 ROUTES 99 条已删）。
表读不到 ⇒ 退出码 3（INCOMPLETE，不判 FAIL、不崩栈）：名单没有来源时**不许**退回写死名单，
那等于把刚拆掉的第二份名单重新长出来。

用法：
  python3 tests/smoke/ux_v3_route_matrix.py                 # 全量（四角色 + admin）
  python3 tests/smoke/ux_v3_route_matrix.py --role stu      # 只跑一个角色
  python3 tests/smoke/ux_v3_route_matrix.py --strict        # WARN 也算失败
  python3 tests/smoke/ux_v3_route_matrix.py --list          # 只读打印名单 + 对账（不连站点、不发请求）
  python3 tests/smoke/ux_v3_route_matrix.py --json /tmp/m.json   # 可选：完整矩阵落盘
  python3 tests/smoke/ux_v3_route_matrix.py --selftest      # 只证量具（夹具走真实读表路径；不连站点）
退出码：0 = 无 FAIL；1 = 有 FAIL；2 = 运行错误（登录失败/服务不可达）；
        3 = INCOMPLETE（tests/ui/surface.json 读不到 —— 名单无来源，口径同 check_ui_surface）。
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests

BASE = 'http://localhost:8069'
DB = 'edu19'

# 角色：key -> (登录名, 密码, 中文名)
# ⚠ admin 的口令：**本库是 demo123，不是 admin**（2026-09-28 B 组实测）。
#   证据：① docs/deploy-malaysia.md:732「为实测编辑器，本地库 admin 口令被设为 demo123（仅本地，
#   生产未动）」；② docs/audit/ui-gap-ledger.md:12 身份行同口径，并点名 backoffice_reachability.py
#   里写的 'admin' 对本库是错的；③ 实测 /web/session/authenticate(admin/admin) → uid=None +
#   "Access Denied"（odoo.addons.base.models.res_users: Login failed for login:admin），
#   而 admin/demo123 → uid=2；④ 用容器内 odoo.tools.config.crypt_context 直接验 res_users.password
#   哈希：verify('demo123', hash)=True，verify('admin', hash)=False。
#   旧值 'admin' 会让整轮门禁在**第 5 个角色**上 exit 2（「运行错误」，且前四角色已跑的读数白跑）——
#   这是环境事实造成的**假红**，不是代码回归；改的是脚本里的**环境凭据**，不是断言强度。
USERS = {
    'stu': ('stu@local', 'demo123', '学生'),
    'fac': ('faculty@local', 'demo123', '教师'),
    'par': ('parent@local', 'demo123', '家长'),
    'bo': ('backoffice@local', 'demo123', '教务'),
    'admin': ('admin', 'demo123', '管理员'),
}
ROLE_ORDER = ['stu', 'fac', 'par', 'bo', 'admin']

# v3 待交付别名/新页（当前 404 → PENDING；交付后由表里这条登记的 gates 决定断言）
# 归属：/login、/apps = t4（brand-eng）；/my/apps、/my/study = t6（study-eng）。
# H-1（2026-09-18）：/my/apps 已交付，且对学生/家长收口为 303 → /my/home
# （内部用户仍 200）⇒ 移出 PENDING_V3；角色级强断言见下方
# REDIRECT_STRICT_BY_ROLE（矩阵的 probe() 跟随重定向，收口在它眼里是假绿）。
PENDING_V3 = {'/login', '/apps', '/my/study'}

ALL5 = {'stu', 'fac', 'par', 'bo', 'admin'}
LOGGED = {'stu', 'fac', 'par', 'bo'}

# ---------------------------------------------------------------- 名单来源（B 组 2026-09-26 切换）
# **单一来源** = tests/ui/surface.json（登记表，A 组维护）：gates 含 route_matrix 的条目就是本门禁
# 的名单。此前这里写死 99 条 ROUTES，与表各写一份 ⇒ 两侧都会落空（新页面谁都扫不到）。
# 切换前逐条对过账（B 组对账表，表指纹 8693d47b）：静态 101 条里 98 条与旧 ROUTES 的
# (path, expect) **逐字相同**（0 处不一致），其余 3 条 = 旧写法里只被强断言块覆盖的别名壳
# （/my/checkin、/my/checkin/export、/my/checkin/save）。于是脚本侧只剩两类**脚本自己的数据**：
#   ① STRICT_SHELLS  —— 覆盖由下方「强断言块」（303 + Location 精确）承载，不重复做常规探；
#   ② SURFACE_MISSING —— 表里**缺登记**、但本门禁一直在真探的路由（绝不静默缩小覆盖）。
# 表里的 roles 直接当「本角色必须 200」的期望集（映射见 ROLE_FROM_SURFACE）。
SURFACE = 'tests/ui/surface.json'
SURFACE_GATE = 'route_matrix'
ROLE_FROM_SURFACE = {'student': 'stu', 'faculty': 'fac', 'parent': 'par',
                     'backoffice': 'bo', 'admin': 'admin'}

# 表缺登记的补偿：**唯一一处手写名单**，每条都要写清为什么表里没有它；补进表后应当删空。
# （为什么不让脚本「表里没有就不扫」：那正好是本次要消灭的静默缩小覆盖 —— 少扫几页 =
#   样本变小 = 假绿，与 check_accessibility 的「可比性守卫」是同一条纪律。）
#
# 2026-09-28（B 组）：**已删空** —— 里面唯一那条 '/' 已经补进表（key=root、gates 含 route_matrix）。
#   删前/删后各跑一遍实测，覆盖没有变小：
#     · 删前：执行集静态 98 条 = 常规探 96 + 强断言壳 2；'/' 经本补偿进探名单，
#       并打印 note「补偿项已进表，建议删掉 SURFACE_MISSING 里的这一条：/」。
#     · 删后：执行集**仍是** 98 条，'/' 改由表行（key=root）进探名单；脚本自己的对账
#       「执行集 − 表 = 空 ｜ 表 − 执行集 = 空」，真机复跑 exit 0（480/480 PASS）。
#   ⇒ 删空正是本机制的设计目标，**不是**放弃 '/' 的覆盖：覆盖真源是表行；表行若被删，
#      表 − 执行集 那条对账会红（本脚本每次运行都打），E 组 check_ui_surface 也会报覆盖缺口。
#      留一个**空白但有说明**的 dict，是为了下次「表里缺登记」时仍有一处显式、可见、
#      必须写理由的手写落点，而不是让脚本静默少扫（少扫=假绿）。
SURFACE_MISSING = {}

# 旧入口别名壳：覆盖由「强断言块」承载（303 + Location 精确，比常规探更强），不重复探；
# 表里这两条的 gates 含 route_matrix 是真的 —— 只是承载机制不同（见每次运行的「对账」输出）。
STRICT_SHELLS = ('/my/checkin/export', '/my/checkin/save')

DYN_SEG_RE = re.compile(r'(/<[^>]+>)+$')


SURFACE_USED = None      # load_surface_routes() 解析出的实际路径（--surface 覆盖时与常量不同；打印用）


def find_surface(override=None):
    """找登记表：--surface 覆盖 ＞ 从本脚本目录**向上**找（不靠 cwd）；找不到返回 None。"""
    if override:
        return override if os.path.isfile(override) else None
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        cand = os.path.join(d, 'tests', 'ui', 'surface.json')
        if os.path.isfile(cand):
            return cand
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    cand = os.path.abspath(SURFACE)
    return cand if os.path.isfile(cand) else None


def surface_fp(path):
    """登记表指纹（内容 md5 前 8 位）—— 让读数能对上「跑的是哪一版表」。"""
    with open(path, 'rb') as fh:
        return hashlib.md5(fh.read()).hexdigest()[:8]


def static_ancestors(path):
    """参数化路由的静态上级候选（长 → 短）：剥尾部动态段 + 逐段上溯。

    与 E 组 check_ui_surface._covered_parent 同口径（按**段边界**，所以 '/my' 不会吞掉
    '/my-library'）。例：'/my/child/<int:child_id>/leave' → ['/my/child/<int:child_id>/leave',
    '/my/child']；调用方取第一个「已在扫描面内」的当上级。
    """
    out = []

    def push(v):
        v = DYN_SEG_RE.sub('', v)
        if v and v != '/' and v not in out:      # '/' 本身不算上级（它是根，不是某一页的上级）
            out.append(v)

    cur = path
    push(cur)
    while '/' in cur[1:]:
        cur = cur.rsplit('/', 1)[0]
        push(cur)
    return out


def load_surface_routes(gate=SURFACE_GATE, path=None):
    """读登记表 → (rows, dyn, fp, err)。

    rows = [(path, expect:set, label)] —— **静态可探**路由（保表序；expect = 表 roles 映射成
           本门禁角色键后的集合；label 用表里的 key，中文备注不再由脚本维护）；
    dyn  = [(path, 上级候选 list)] —— 带 <参数> 的登记：**不能裸探**（探 '/x/<int:id>' 只会拿
           404，表侧 evidence 也写明「非直探本页，覆盖经上级继承」），这里只核对上级是否真在
           扫描面内；
    err  = 读不到 / 解析失败时的**人话原因**（调用方判 INCOMPLETE：不判 FAIL、不崩栈，
           也**不**退回写死名单 —— 那等于把刚拆掉的第二份名单重新长出来）。
    """
    global SURFACE_USED
    path = find_surface(path)
    if not path:
        return None, None, None, '文件不存在（%s）' % SURFACE
    SURFACE_USED = path
    try:
        with open(path, encoding='utf-8') as fh:
            doc = json.load(fh)
        pages = doc['pages']
        if not isinstance(pages, list):
            raise ValueError('pages 不是列表')
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return None, None, None, '读不出 / 解析失败（%s: %s）' % (SURFACE, exc)
    rows, dyn = [], []
    for rec in pages:
        if not isinstance(rec, dict):
            continue
        p = (rec.get('path') or '').strip()
        if not p or gate not in (rec.get('gates') or []):
            continue
        if '<' in p:
            dyn.append((p, static_ancestors(p)))
            continue
        expect = set(ROLE_FROM_SURFACE[r] for r in (rec.get('roles') or [])
                     if r in ROLE_FROM_SURFACE)
        rows.append((p, expect, rec.get('key') or p))
    return rows, dyn, surface_fp(path), None


def build_scan(rows, dyn):
    """表 → 扫描面。返回 (probe, skipped_shells, missing, table_only, dyn_rows, notes)。

    · probe         = [(path, expect, label)]：**真会发请求**的常规探名单
    · skipped_shells= 表里登记、但由强断言块承载的别名壳（不重复探，覆盖照样算数）
    · missing       = SURFACE_MISSING 里**表还没有**的补偿项（表缺登记，仍在本门禁扫描面内）
    · table_only    = 表登记了、但本门禁**不执行**的静态路径（覆盖虚报，必须为空）
    · dyn_rows      = [(path, 上级 or '')]：上级取自扫描面；空 ⇒ 覆盖缺口
    """
    probe = [(p, e, l) for p, e, l in rows if p not in STRICT_SHELLS]
    skipped_shells = [p for p, _e, _l in rows if p in STRICT_SHELLS]
    table_paths = set(p for p, _e, _l in rows)
    missing, notes = [], []
    for p, (expect, why) in sorted(SURFACE_MISSING.items()):
        if p in table_paths:
            notes.append('补偿项已进表，建议删掉 SURFACE_MISSING 里的这一条：%s' % p)
            continue
        probe.append((p, expect, why))
        missing.append(p)
    exec_paths = (set(p for p, _e, _l in probe)
                  | set(p for p, _c, _l in REDIRECT_STRICT)
                  | set(p for p, _r, _w, _l, _y in REDIRECT_STRICT_BY_ROLE))
    table_only = sorted(p for p in table_paths if p not in exec_paths)
    dyn_rows = [(p, next((c for c in cands if c in exec_paths), '')) for p, cands in dyn]
    return probe, skipped_shells, missing, table_only, dyn_rows, notes


def print_coverage(fp, rows, probe, skipped_shells, missing, table_only, dyn_rows, notes):
    """打印「名单从哪来 / 执行了什么 / 两处不一致」—— **每次跑都打**，防止名单悄悄漂移。"""
    reg_static = [p for p, _e, _l in rows]
    probe_paths = [p for p, _e, _l in probe]
    strict_paths = [p for p, _c, _l in REDIRECT_STRICT]
    exec_paths = (set(probe_paths) | set(strict_paths)
                  | set(p for p, _r, _w, _l, _y in REDIRECT_STRICT_BY_ROLE))
    print('名单来源：%s（指纹 %s）· gates=route_matrix 登记 %d 条 = 静态 %d + 参数化 %d'
          % (SURFACE_USED or SURFACE, fp, len(rows) + len(dyn_rows), len(rows), len(dyn_rows)))
    print('  执行集：静态 %d 条 = 常规探 %d + 强断言块 %d（去重后）｜参数化 %d 条不裸探'
          % (len(exec_paths), len(probe_paths), len(set(strict_paths) - set(probe_paths)),
             len(dyn_rows)))
    print('  对账：执行集 − 表 = %s ｜ 表 − 执行集 = %s'
          % ('、'.join(sorted(set(exec_paths) - set(reg_static))) or '（空 = 无表外执行）',
             '、'.join(sorted(set(reg_static) - set(exec_paths))) or '（空 = 无虚报登记）'))
    if missing:
        print('  ⚠ 表缺登记 %d 条（本门禁仍在执行，**不许静默缩小覆盖**）：' % len(missing))
        for p in missing:
            print('      · %s —— %s' % (p, SURFACE_MISSING[p][1]))
    if table_only:
        print('  ⚠ 表登记但本门禁不执行 %d 条（覆盖虚报，需处置）：%s'
              % (len(table_only), '、'.join(table_only)))
    nodyn = [p for p, par in dyn_rows if not par]
    if dyn_rows:
        print('  参数化 %d 条：静态上级在扫描面内 %d 条%s'
              % (len(dyn_rows), len(dyn_rows) - len(nodyn),
                 '' if not nodyn else '｜⚠ 无上级 %d 条（覆盖缺口）：%s'
                 % (len(nodyn), '、'.join(nodyn))))
    empty_expect = [p for p, e, _l in probe if not e]
    if empty_expect:
        print('  ⚠ 表 roles 与探针角色无交集 %d 条（只判「不 5xx / 不 404」，不判必须 200）：%s'
              % (len(empty_expect), '、'.join(sorted(empty_expect))))
    for n in notes:
        print('  note：%s' % n)


def print_list(rows, probe, skipped_shells, missing, table_only, dyn_rows, fp):
    """--list：**只读**打印名单与对账（不连站点、不发请求）；机器可读前缀 TAG 供对账脚本取用。"""
    print('== 名单（只读打印；单一来源 = %s）==' % (SURFACE_USED or SURFACE))
    print('指纹 %s ｜ gates=route_matrix 登记 %d 条 = 静态 %d + 参数化 %d'
          % (fp, len(rows) + len(dyn_rows), len(rows), len(dyn_rows)))
    print('-- 表登记（静态，本门禁可探）--')
    for p, expect, label in rows:
        print('[TABLE] %-32s expect=%-38s key=%s'
              % (p, ','.join(sorted(expect)) or '(无)', label))
    print('-- 强断言块（303 + Location 精确）--')
    for p, code, loc in REDIRECT_STRICT:
        print('[STRICT] %-31s %s -> %s' % (p, code, loc))
    print('-- 表缺登记补偿（本门禁仍在扫）--')
    for p, (expect, why) in sorted(SURFACE_MISSING.items()):
        if p in [q for q, _e, _l in rows]:
            print('[MISSING] %-30s （已进表，可删补偿）%s' % (p, why))
        else:
            print('[MISSING] %-30s expect=%s  %s' % (p, ','.join(sorted(expect)), why))
    print('-- 参数化登记（不可裸探；登记语义 = 覆盖经上级继承）--')
    for p, par in dyn_rows:
        print('[DYN] %-36s 静态上级=%s' % (p, par or '⚠ 无（在扫描面内找不到上级）'))
    print('-- 对账 --')
    reg = set(p for p, _e, _l in rows)
    ex = (set(p for p, _e, _l in probe) | set(p for p, _c, _l in REDIRECT_STRICT)
          | set(p for p, _r, _w, _l, _y in REDIRECT_STRICT_BY_ROLE))
    print('执行集 − 表 = %s' % ('、'.join(sorted(ex - reg)) or '（空）'))
    print('表 − 执行集 = %s' % ('、'.join(sorted(table_only)) or '（空）'))
    print('常规探名单（切换前/后逐条对账用；不含强断言路径）：')
    for p, expect, _label in probe:
        print('[PROBE] %-32s expect=%s' % (p, ','.join(sorted(expect)) or '(无)'))
    print('== 退出码 0 = 名单读得到（--list 只打印，不判门禁）==')
    return 0


ERR_MARKS = ('Traceback (most recent call last)', 'Internal Server Error',
             'odoo.exceptions.', 'werkzeug.exceptions.')

# t5/t9：旧打卡入口已收口，必须 303 且 Location 精确指向新入口。
# 为什么单独做：probe() 默认 allow_redirects=True、verdict() 只看 final==200，
# 所以“旧路径改 303”这类改动在矩阵里不会变红，只会变成假绿。
# 这里用 allow_redirects=False 直接读 Location，抬不起这个级别的绕过不了。
REDIRECT_STRICT = [
    ('/my/checkin', 303, '/my/checkins'),
    ('/my/checkin/export', 303, '/my/checkins/export'),
    ('/my/checkin/save', 303, '/my/checkins'),
]

# H-1（校长拍板 2026-09-18，学生门户主页合并）：/my/apps 对学生/家长收口为
# 303 → /my/home。2026-10-03（用户要求「老师的我的主页和应用面板功能可以
# 合并，不要分开了」）：**教师**同样收口 303 → /my/home（工作台 + 宫格已在
# 同页）；**教务仍 200**（他们在门户里仍只有这一条宫格入口）。
# 这里按角色分别强断言：
#   303 侧 = 码 303 + Location 精确 /my/home；200 侧 = 直接 200（不跟跳转）。
# 为什么要单列：probe() 默认 allow_redirects=True、verdict() 只看 final==200，
# 所以"旧入口改成 303"在矩阵里永远 PASS（假绿）——见 dev-workflow 陷阱 2。
REDIRECT_STRICT_BY_ROLE = [
    ('/my/apps', 'stu', 303, '/my/home', '学生：宫格已合并进 /my/home'),
    ('/my/apps', 'par', 303, '/my/home', '家长：同上'),
    ('/my/apps', 'fac', 303, '/my/home', '教师：工作台+宫格已并入 /my/home（2026-10-03）'),
    ('/my/apps', 'bo', 200, None, '教务：门户宫格入口不变'),
]


def health_check():
    """三步探活（队长 2026-09-12 定的纪律，多库环境必需）：

    1) 没有升级锁 —— 并发升级会让 registry 半加载；
    2) 容器不是刚重启（Up < 30s 不跑，避免半启动状态）；
    3) 带库名探活：/web/login?db=edu19 与 /login?db=edu19（带 cookie jar）必须 200/302/303。
       本地有 2+ 个库且 list_db=False 时，不带库名的请求会落 nodb 路由表
       （表现为 404 / 自跳 302），很容易被误读成「全站崩」。
    """
    import os
    # 升级锁口径（t9 统一，与 scripts/safe_upgrade.sh:60 / tests/smoke/authz_endtoend_smoke.py:107 同源）：
    #   EDU_UPGRADE_LOCK 覆盖 ＞ TMPDIR（未设**或空** ⇒ /tmp）＞ 固定名 edu19_upgrade.lock。
    # 旧写法 os.environ.get('TMPDIR', '/tmp') 在 TMPDIR="" 时退化成**相对路径**
    # 'edu19_upgrade.lock' ⇒ 锁在也看不见（fail-open，t9 实测）；末尾 isabs 自检兜底。
    # 存在性判据用 exists 而非 isdir：与 t5 修好的 authz/check_view_xpath 同口径（宁可多拦一次）。
    lock = (os.environ.get('EDU_UPGRADE_LOCK')
            or os.path.join(os.environ.get('TMPDIR') or '/tmp',
                            'edu19_upgrade.lock'))
    if not os.path.isabs(lock):
        lock = '/tmp/edu19_upgrade.lock'
    if os.path.exists(lock):
        return '升级锁存在（%s）—— 有人的 safe_upgrade.sh 正在跑，别开测' % lock
    try:
        import subprocess
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run(['docker', 'compose', 'ps', '--format', '{{.Name}} {{.Status}}'],
                             capture_output=True, text=True, timeout=15, cwd=root)
        for line in out.stdout.splitlines():
            if 'web-1' in line and ' Up ' in line:
                m = re.search(r'Up (\d+) seconds', line)
                if m and int(m.group(1)) < 30:
                    return 'web 容器刚重启（Up %ss < 30s）—— 等稳定再跑' % m.group(1)
    except Exception:
        pass  # 没有 docker CLI 时跳过这一步，不影响其余探活
    s = requests.Session()
    s.trust_env = False
    for path in ('/web/login?db=edu19', '/login?db=edu19'):
        try:
            r = s.get(BASE + path, timeout=15, allow_redirects=False)
        except Exception as e:
            return '服务不可达（%s）: %s' % (path, str(e)[:60])
        if r.status_code not in (200, 302, 303):
            return ('%s 返回 %s —— 多库环境未选库 / registry 未加载？'
                    '先看 docker compose logs web --tail 40' % (path, r.status_code))
    return None


def login(user_key):
    """带 cookie jar（requests.Session 自动管理 session_id）登录，失败重试一次。

    说明：Odoo 必须先选定数据库（session.db）。JSON-RPC 显式带 db 参数即等价于
    「选库 + 登录」，不需要先 GET /web/login?db=edu19 —— 后者在无 cookie 时会
    302 回自己（选库跳转），脚本若拿它当健康探针会误判为死循环。
    """
    login_name, pwd, _ = USERS[user_key]
    s = requests.Session()          # ← cookie jar：session_id 全程复用
    s.trust_env = False
    s.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    last_err = ''
    for attempt in (1, 2):
        try:
            r = s.post(BASE + '/web/session/authenticate', json={
                'jsonrpc': '2.0',
                'params': {'db': DB, 'login': login_name, 'password': pwd},
            }, timeout=25)
            payload = r.json()
            uid = (payload.get('result') or {}).get('uid')
            if uid:
                return s, None
            err = payload.get('error') or {}
            last_err = 'HTTP %s %s' % (r.status_code,
                                       (err.get('data', {}).get('message')
                                        or err.get('message') or '无 uid'))
        except Exception as e:
            last_err = '登录异常 %s' % str(e)[:80]
        if attempt == 1:
            time.sleep(5)           # registry 正在加载时给一次重试窗口
    return None, last_err or '登录失败'


def probe(sess, path):
    """返回 dict(first, hist, final, final_path, marks, ms, error)。"""
    t0 = time.time()
    try:
        r = sess.get(BASE + path, timeout=40, allow_redirects=True)
    except Exception as e:
        return dict(error='%s: %s' % (type(e).__name__, str(e)[:80]),
                    ms=int((time.time() - t0) * 1000))
    body = r.text or ''
    return dict(
        first=r.history[0].status_code if r.history else r.status_code,
        hist=[h.status_code for h in r.history],
        final=r.status_code,
        final_path=urlparse(r.url).path,
        marks=[m for m in ERR_MARKS if m in body],
        bytes=len(body),
        ms=int((time.time() - t0) * 1000),
    )


def verdict(path, role, expect, res):
    """返回 (verdict, note)。verdict ∈ PASS/PENDING/WARN/FAIL/ENV。

    ENV = 请求异常（ConnectionError/timeout）—— 升级重启窗口的典型症状，
    与「代码回归」严格区分：ENV 不计 FAIL，但会让整份样本作废（见 main 退出码）。
    """
    if 'error' in res:
        return 'ENV', '请求异常 %s' % res['error']
    codes = res['hist'] + [res['final']]
    if res['marks']:
        return 'FAIL', '响应含错误标记: %s' % '/'.join(res['marks'])
    if any(c >= 500 for c in codes):
        return 'FAIL', 'HTTP %s（服务端错误）' % '/'.join(str(c) for c in codes)
    if res['final'] == 404:
        if path in PENDING_V3:
            return 'PENDING', 'v3 待交付（当前 404）'
        return 'WARN', '404 路由缺失'
    if res['final'] == 403:
        return 'WARN', '403 权限拒绝（应 303 分流）'
    if role in expect and res['final'] != 200:
        return 'FAIL', '本角色应 200，实际 %s（跳转链 %s）' % (
            res['final'], '→'.join(str(c) for c in codes))
    if res['final'] == 200:
        if res['final_path'].endswith('/web/login') or res['final_path'] == '/login':
            return 'WARN', '被弹回登录页（会话/权限异常）'
        if role in expect and res['final'] != 200:
            return 'FAIL', '应 200 未达成'
        return 'PASS', ('跳转 ' + '→'.join(str(c) for c in codes)) if len(codes) > 1 else '直接 200'
    return 'WARN', '最终 %s（未达 200 且非 404）' % res['final']


def cell(res):
    if 'error' in res:
        return 'EXC'
    codes = res['hist'] + [res['final']]
    s = '→'.join(str(c) for c in codes)
    if res['marks'] or any(c >= 500 for c in codes):
        return s + '!'
    return s


# ---------------------------------------------------------------- 自证（不连站点 / 不发请求）
# 本仓纪律：**改了门禁脚本就要有能报红的自证**；夹具与实物逐字同形，且自证必须证明
# 「检查失败能改变结论」（下面 ③ 专门证明对账检测器真会报红，不是永远绿的装饰）。
SELFTEST_DECLARED = 19


def _fixture_page(key, path, gates, roles=('student',)):
    """夹具行：字段与真表**逐字同形**（真表由 ui_surface_report.py 的 surface_doc() 产出）。"""
    return dict(key=key, path=path, module='edu_fixture', kind='page', scope='portal',
                roles=list(roles), gates=list(gates), pending_gate='', reason='',
                status='unverified', evidence='')


def _write_fixture(path, pages):
    doc = {'surface-version': 'v1', 'generated': '2026-09-28',
           'source': 'custom_addons/**/*.py :: @http.route', 'pages': pages}
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)


def selftest():
    """离线自证：名单解析 / 门禁过滤 / 角色映射 / 对账 / 缺登记补偿 / 缺表护栏。

    为什么不喂内存对象而写成**临时目录里的真 JSON**：这样走的是生产同一条代码路径
    （find_surface → 读文件 → 解析）—— 夹具自洽但和生产不同形的话，绿也不算数。
    """
    import io
    import shutil
    import tempfile
    from contextlib import redirect_stdout
    global SURFACE_MISSING, REDIRECT_STRICT
    checks = []

    def chk(name, got, want):
        checks.append((name, got == want, got, want))

    tmp = tempfile.mkdtemp(prefix='ux_matrix_selftest_')
    try:
        good = os.path.join(tmp, 'surface.json')
        _write_fixture(good, [
            _fixture_page('x_one', '/x/one', ['route_matrix'], ('student', 'faculty', 'anon')),
            _fixture_page('x_eng', '/x/two', ['english'], ('student',)),
            _fixture_page('x_dyn', '/x/one/<int:rid>', ['route_matrix'], ('parent',)),
            _fixture_page('x_shell', '/my/checkin/save', ['route_matrix'], ('student',)),
        ])
        rows, dyn, fp, err = load_surface_routes(path=good)
        chk('① 读表成功（err 为空）', err, None)
        chk('① 指纹算得出（8 位 md5）', isinstance(fp, str) and len(fp) == 8, True)
        chk('① 只收 gates 含本门禁的行（/x/two 被剔除）',
            [r[0] for r in rows], ['/x/one', '/my/checkin/save'])
        chk('① 角色映射：匿名不进期望集、短键正确', rows[0][1], {'stu', 'fac'})
        chk('① 参数化行进 dyn（不裸探）', [d[0] for d in dyn], ['/x/one/<int:rid>'])

        probe, shells, missing, table_only, dyn_rows, notes = build_scan(rows, dyn)
        chk('② 强断言壳被摘出常规探', shells, ['/my/checkin/save'])
        chk('② 常规探 = 表内非壳行', [p for p, _e, _l in probe], ['/x/one'])
        chk('② 参数化上级落在扫描面内', dyn_rows, [('/x/one/<int:rid>', '/x/one')])
        chk('② 对账：表 − 执行集 = 空（无虚报）', table_only, [])
        chk('② 对账：执行集 − 表 = 空（无表外执行）', missing, [])

        # ③ 对账检测器**能报红**：清空强断言表 ⇒ 壳行既不在常规探、也不在强断言里，
        #    必须被点名成「表登记但本门禁不执行」，而不是静默算作覆盖。
        keep_redirect = REDIRECT_STRICT
        try:
            REDIRECT_STRICT = []
            _p, _s, _m, only, _d, _n = build_scan(rows, dyn)
        finally:
            REDIRECT_STRICT = keep_redirect
        chk('③ 反例：壳行失去强断言承载 ⇒ 对账报「登记但未执行」', only, ['/my/checkin/save'])

        # ④ 缺登记补偿机制仍在（删空的是**内容**，不是机制）：表里没有的路径只有写进
        #    SURFACE_MISSING 才被真探并被点名；补进表后反过来提示删补偿、且不重复计数。
        keep_missing = SURFACE_MISSING
        try:
            SURFACE_MISSING = {'/x/comp': ({'stu'}, '夹具：表里没有它，故走补偿')}
            p2, _s2, m2, _t2, _d2, _n2 = build_scan(rows, dyn)
            chk('④ 补偿项进了探名单', '/x/comp' in [p for p, _e, _l in p2], True)
            chk('④ 补偿项被点名（不许静默）', m2, ['/x/comp'])
            comp = os.path.join(tmp, 'surface_comp.json')
            _write_fixture(comp, [_fixture_page('x_comp', '/x/comp', ['route_matrix'], ('student',))])
            rows3, dyn3, _fp3, _e3 = load_surface_routes(path=comp)
            p3, _s3, m3, _t3, _d3, n3 = build_scan(rows3, dyn3)
            chk('④ 补偿项已进表 ⇒ 不再重复计入 missing', m3, [])
            chk('④ 补偿项已进表 ⇒ 提示删掉补偿',
                any('建议删掉 SURFACE_MISSING' in x for x in n3), True)
            chk('④ 补偿项已进表 ⇒ 探名单里只出现一次',
                [p for p, _e, _l in p3].count('/x/comp'), 1)
        finally:
            SURFACE_MISSING = keep_missing

        # ⑤ 缺表护栏：表读不到 ⇒ 名单没有来源，**不退回写死名单**（exit 3 契约）
        _r, _d, _f, miss_err = load_surface_routes(path=os.path.join(tmp, 'nope.json'))
        chk('⑤ 表不存在 ⇒ 返回人话原因（调用方判 INCOMPLETE）', bool(miss_err), True)
        saved = sys.argv
        buf = io.StringIO()
        try:
            sys.argv = ['ux_v3_route_matrix.py', '--surface',
                        os.path.join(tmp, 'nope.json'), '--list']
            with redirect_stdout(buf):
                rc = main()
        finally:
            sys.argv = saved
        chk('⑤ 表读不到 ⇒ main() 返回 3（INCOMPLETE，不是 0）', rc, 3)
        chk('⑤ 且明说不退回写死名单', '不退回写死名单' in buf.getvalue(), True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bad = [c for c in checks if not c[1]]
    for name, ok, got, want in checks:
        print('  %-4s %-56s 期望 %r 实际 %r' % ('PASS' if ok else 'FAIL', name, want, got))
    print('== 自证 %s ==（断言 %d 条 / 声明 %d 条）'
          % ('通过' if not bad else '失败', len(checks), SELFTEST_DECLARED))
    if len(checks) != SELFTEST_DECLARED:
        print('  FAIL 自证条数与声明不一致 —— 少证等于没证')
        return 1
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description='v3 路由 × 角色矩阵门禁')
    ap.add_argument('--role', action='append', choices=ROLE_ORDER, help='只跑指定角色')
    ap.add_argument('--strict', action='store_true', help='WARN 也视为失败')
    ap.add_argument('--json', dest='json_out', default=None,
                    help='把完整矩阵落盘 JSON（默认不写文件，避免污染工作区）')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--list', action='store_true',
                    help='只读打印名单 + 对账（不连站点、不发请求）')
    ap.add_argument('--selftest', action='store_true',
                    help='只证量具（名单解析 / 对账 / 缺登记补偿 / 缺表护栏；不连站点、不发请求）')
    ap.add_argument('--surface', default=None,
                    help='登记表路径（默认 tests/ui/surface.json）—— 审读/按冻结快照复算用')
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    # ---- 名单来源：tests/ui/surface.json（单一来源；B 组 2026-09-26 切换）----
    rows_t, dyn, fp, serr = load_surface_routes(path=args.surface)
    if serr:
        print('INCOMPLETE：%s %s' % (SURFACE, serr))
        print('  名单没有来源 ⇒ 本轮**不扫、不判 FAIL**（退出码 3）。登记表由 A 组维护，'
              '生成：python3 scripts/ui_surface_report.py --generate')
        print('  这里**不退回写死名单** —— 那等于把刚拆掉的第二份名单重新长出来。')
        return 3
    # ⚠ 名字别用 probe：那个名字是模块级函数 probe()，局部同名会遮蔽它（本轮实测踩过一次）
    probe_rows, skipped_shells, missing, table_only, dyn_rows, notes = build_scan(rows_t, dyn)
    if args.list:
        return print_list(rows_t, probe_rows, skipped_shells, missing, table_only, dyn_rows, fp)
    # 先打「名单从哪来 / 扫什么」：探活或登录失败时也能看到本轮的名单版本与规模（不猜、不静默）
    print_coverage(fp, rows_t, probe_rows, skipped_shells, missing, table_only, dyn_rows, notes)

    err = health_check()
    if err:
        print('无法继续：%s' % err)
        return 2

    roles = args.role or ROLE_ORDER
    sessions = {}
    for rk in roles:
        sess, err = login(rk)
        if err:
            print('无法继续：角色 %s（%s）%s' % (rk, USERS[rk][0], err))
            return 2
        sessions[rk] = sess
    print('登录 OK：' + '，'.join('%s(%s)' % (rk, USERS[rk][0]) for rk in roles))
    print('路由 %d 条 × 角色 %d 个 = %d 次检查\n'
          % (len(probe_rows), len(roles), len(probe_rows) * len(roles)))

    rows = []
    counts = {'PASS': 0, 'PENDING': 0, 'WARN': 0, 'FAIL': 0, 'ENV': 0}
    # t9：旧入口的严格重定向断言（不跟随，直读 Location）
    redirect_rows = []
    redirect_fail = 0
    for path, expect, label in probe_rows:
        row = dict(path=path, label=label, expect=sorted(expect), cells={}, verdicts={})
        for rk in roles:
            res = probe(sessions[rk], path)
            v, note = verdict(path, rk, expect, res)
            row['cells'][rk] = cell(res)
            row['verdicts'][rk] = dict(verdict=v, note=note, **{
                k: v2 for k, v2 in res.items() if k != 'error'})
            counts[v] += 1
        # 行级判定：最差者胜
        worst = 'PASS'
        for rk in roles:
            v = row['verdicts'][rk]['verdict']
            if v == 'FAIL':
                worst = 'FAIL'
            elif v in ('WARN', 'ENV') and worst == 'PASS':
                worst = 'WARN'
        row['verdict'] = worst
        rows.append(row)
        if not args.quiet:
            notes = ['%s:%s' % (rk, row['verdicts'][rk]['note'])
                     for rk in roles if row['verdicts'][rk]['verdict'] in ('FAIL', 'WARN', 'PENDING')]
            print('%-4s %-30s %s  %s' % (row['verdict'], path,
                                         ' '.join('%-9s' % row['cells'][rk] for rk in roles),
                                         ' | '.join(notes)[:110]))


    # ---- t9：旧打卡入口必须 303 + Location 精确（防假绿）----
    # 不用 probe()：它默认跟随重定向，“转过去后 200”会把“旧路径还在干活”也判成 PASS。
    for _path, _want_code, _want_loc in REDIRECT_STRICT:
        _bad = []
        _cells = {}
        for rk in roles:
            try:
                _r = sessions[rk].get(BASE + _path, timeout=30,
                                      allow_redirects=False)
                _code = _r.status_code
                _loc = _r.headers.get('Location', '')
            except Exception as _e:
                _code, _loc = -1, 'EXC:%s' % type(_e).__name__
            _ok = (_code == _want_code and _loc.endswith(_want_loc))
            _cells[rk] = '%s->%s' % (_code, _loc or '-')
            if not _ok:
                _bad.append('%s:%s' % (rk, _cells[rk]))
        redirect_fail += 1 if _bad else 0
        redirect_rows.append((_path, not _bad, _bad, _cells))
        if not args.quiet:
            print('%-4s %-24s 强断言 %s %s' % ('PASS' if not _bad else 'FAIL',
                  _path, _want_code, _want_loc))
            if _bad:
                print('       不符合角色：' + '；'.join(_bad))

    # ---- H-1：/my/apps 按角色的强断言（303 收口 vs 内部用户 200）----
    role_strict_fail = 0
    for _path, _role, _want, _want_loc, _why in REDIRECT_STRICT_BY_ROLE:
        if _role not in roles:
            continue
        try:
            _r = sessions[_role].get(BASE + _path, timeout=30,
                                     allow_redirects=False)
            _code, _loc = _r.status_code, _r.headers.get('Location', '')
        except Exception as _e:
            _code, _loc = -1, 'EXC:%s' % type(_e).__name__
        if _want == 200:
            _ok = (_code == 200)
        else:
            _ok = (_code == _want and _loc.endswith(_want_loc))
        if not _ok:
            role_strict_fail += 1
        if not args.quiet:
            print('%-4s %-11s [%s] 强断言 %s %s  %s  <- %s' % (
                'PASS' if _ok else 'FAIL', _path, _role, _want or '200',
                _want_loc or '-', '%s->%s' % (_code, _loc or '-'), _why))

    n_fail = counts['FAIL']
    n_warn = counts['WARN']
    n_pend = counts['PENDING']
    n_pass = counts['PASS']
    n_env = counts['ENV']
    total = len(roles) * len(probe_rows)
    print('\n============ 汇总 ============')
    print('旧打卡入口强断言（303 + Location 精确）：%d 条 / 失败 %d' % (len(redirect_rows), redirect_fail))
    print('H-1 /my/apps 角色强断言（学生/家长 303 + Location 精确；内部用户 200）：失败 %d'
          % role_strict_fail)
    print('检查点 %d：PASS %d / WARN %d / PENDING %d / FAIL(真红) %d / ENV(环境) %d'
          % (total, n_pass, n_warn, n_pend, n_fail, n_env))
    if n_pend:
        print('PENDING（v3 待交付，交付后自动纳入断言）：' + '、'.join(sorted(PENDING_V3)))
    if n_env:
        print('\n-- ENV 明细（请求异常，环境故障；不计 FAIL）--')
        for row in rows:
            for rk in roles:
                info = row['verdicts'][rk]
                if info['verdict'] == 'ENV':
                    print('  %-28s [%s] %s' % (row['path'], rk, info['note'][:90]))
    if n_fail:
        print('\n-- FAIL 明细（真红）--')
        for row in rows:
            for rk in roles:
                info = row['verdicts'][rk]
                if info['verdict'] == 'FAIL':
                    print('  %-28s [%s] %s' % (row['path'], rk, info['note']))
    if n_warn:
        print('\n-- WARN 明细 --')
        for row in rows:
            for rk in roles:
                info = row['verdicts'][rk]
                if info['verdict'] == 'WARN':
                    print('  %-28s [%s] %s' % (row['path'], rk, info['note']))

    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as f:
            json.dump(dict(base=BASE, roles=roles, counts=counts, pending=sorted(PENDING_V3),
                           redirect_strict=[{'path': p2, 'ok': ok,
                                             'mismatch': bad, 'cells': cells}
                                            for p2, ok, bad, cells in redirect_rows],
                           rows=rows, generated=time.strftime('%Y-%m-%d %H:%M:%S')),
                      f, ensure_ascii=False, indent=1)
        print('-> %s' % args.json_out)

    if n_fail or redirect_fail or role_strict_fail:
        return 1
    if n_env >= max(5, total // 10):
        print('\n[!] ENV %d 条（≥10%%）—— 采样窗口里服务在重启，**本份样本作废**；'
              '等三步探活通过（无锁 / 容器 Up>30s / 带 cookie 探活 200/302/303）后重跑。' % n_env)
        return 2
    if args.strict and n_warn:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
