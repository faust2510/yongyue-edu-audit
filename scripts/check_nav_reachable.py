# -*- coding: utf-8 -*-
"""导航可达性核查（t10 建；t85 换输入源）：导航的每个目标在**游客态**与**登录态**是否都 200。

## 一、契约（t85 判定）：**活的导航树**，不是设计规格
本门禁问的是"**站点现在真实渲染出的导航里，有没有指向死页的链接**"，
⇒ 输入必须来自**实时状态**。本脚本直接读 website.menu（渲染导航用的就是这个模型/这张表）。

为什么"仓内那份 JSON"**不是**契约的一部分（逐条可复算）：
1. docs/audit/menu-consolidation/nav-tree-after.json 是**实测快照**，不是规格：
   它由 scripts/fix_nav_duplicates.py 的 --export 分支调用 dump_tree()
   （= kw('website.menu','search_read', ...)）**从活表导出**；t10 文档把它登记为
   "导出为证"（docs/audit/nav-consolidation-t10.md:13、:22「导出文件」）。
2. 本仓导航的**唯一声明源/规格**是 docs/audit/menu-consolidation/menu-consolidation-plan.json
   ＋ custom_addons/edu_nav/（docs/audit/menu-nav-handoff.md:38、:66）；
   那份快照从未被登记为"计划中的导航树"。
3. 判据句本身以 **website.menu** 为准（docs/audit/nav-consolidation-t10.md:33），
   而 website.menu 是**活模型**；文件只是它某一刻的序列化 —— 序列化会过时，模型不会。

## 二、事故（t85，实测 2026-09-28）：输入失效 ⇒ 红在假问题上
提交 f70d86b（修凭据 + 明细 IndexError）之后本门禁 exit 1，报 5 条 404 并称之为"真问题"。
实测这 5 条是**假警报**：
- website_slides / website_event / website_forum / website_blog / website_sale 五模块
  在本库全部 uninstalled（前端瘦身整族卸载，6e5e53c）；
- 活库 website.menu 27 行里**一条都不含**这 5 个 url（按 url 查为空集）；
- 游客首页 HTML 里这 5 个 href 出现 **0 次**；本仓 custom_addons/**/*.xml 里同样 **0 次**。
快照里命中死链的是 **12 行**（同一条 url 在 parent 1 与 4 两个根下各一份）。
⇒ 红的原因不是"站点坏了"，是"**快照停在 2026-09-17**"。这种红与"坏了却是绿的"同罪：
两者都会毁掉门禁的可信度。

## 三、改法与不变量（换的是**输入来源**，判据一行没动）
- 默认输入：活表 website.menu（JSON-RPC search_read，model/字段/排序与
  fix_nav_duplicates.dump_tree() **完全同口径** —— 换源不是换口径）；
- 活表读不到（未登录 / 被拒 / 站点不通）⇒ 退出码 2（**不判通过**），
  **绝不回落到仓内快照**：静默回落正是本次事故的成因；
- 输入源给出 0 条目标 ⇒ 退出码 2（空输入不判通过；旧版文件缺失时会静默 0 条并 PASS）；
- 请求打不到站点（连接错误等）⇒ 该列记"未验证"，**不记"不可达"**（旧版会直接抛栈崩掉）；
- 判据 / 阈值 / 退出码语义 / ALLOW_REDIRECT 例外机制 / 两列探测：**逐条保留**，断言未删。

## 玩法
    python3 scripts/check_nav_reachable.py              # 默认：活表输入 + 逐条探测（游客/登录）
    python3 scripts/check_nav_reachable.py --selftest   # 正反双向自证：先证量具，再读数

退出码（t81；优先级与同族门禁 check_odoo_trace.py 一致：命中 1 > 未验证 2）：
  0 = 游客态 + 登录态**两列都已验证**且全部可达；
  1 = 有目标确实不可达（游客态就已确认的，或登录态已验证但未达 200）；
  2 = 本轮**未验证**：活表输入读不到 / 输入源 0 条目标 / 登录态这一列没看成 /
      请求打不到站点 —— "这次没看成"，既不是通过、也不是"导航真的坏了"。

环境变量：
- EDU_ADMIN_LOGIN / EDU_ADMIN_PASSWORD  覆盖登录凭据（口令不打印）；
- EDU_NAV_TREE=<path>  **只为正反双向自证**：用注入夹具替代活表。设了它就**不读活表、
  也不代表站点状态**（输出带醒目横幅），判据本身不变。夹具格式：JSON 数组
  [{"id":..,"name":..,"url":..}, ...]（--selftest 就是用它证的）。
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tests/audit'))
import audit_lib as A  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 与 scripts/fix_nav_duplicates.py 的 dump_tree() 同口径（同 model / 同字段 / 同排序）：
# 换输入来源**不是**换口径 —— 注入夹具与活表都走这一套字段。
FIELDS = ['id', 'name', 'url', 'parent_id', 'sequence', 'website_id', 'page_id']
SKIP_URLS = ('#', '/')

# ---- 凭据：**唯一声明点**（t81；t85 未新增第二处）----
# 口令只在这里出现，且**不打印**（打印只出现登录名）。
ADMIN_LOGIN = os.environ.get('EDU_ADMIN_LOGIN', 'admin')
ADMIN_PASSWORD = os.environ.get('EDU_ADMIN_PASSWORD', 'demo123')

# 判据（比"一律 200"更贴合真实可达性，且把已知设计性跳转显式登记）：
#   1) 直接 200 → 通过；
#   2) 302/303 但**跟随跳转后仍 200** 且在例外清单里 → 通过；
#   3) 404/5xx 或跟随跳转后非 200 → 失败；
#   4) 例外清单必须写明**为什么跳转是设计**，否则算失败。
ALLOW_REDIRECT = {
    '/my-courses': '登录门禁：游客 303 → /web/login（受保护页），登录后 200',
    '/login': '登录页：已登录时 303 → /web（原生行为）',
    '/forum': '历史登记（t10 当时 website_forum 在位：302 → 唯一论坛 /forum/帮助-1）。'
              '本库 website_forum 已 uninstalled ⇒ 该条现在只在"注入夹具 / 将来重装"时才会被用到；'
              '判据未变：仍须"302/303 且跟随跳转后 200"才算通过。',
}


def _targets(tree):
    """去重后的待核目标：(id, name, url)。口径与旧版一致（跳过空 / "#" / "/" / 纯锚点）。"""
    seen, targets = set(), []
    for m in tree or []:
        u = (m.get('url') or '').strip()
        if not u or u in SKIP_URLS or u.startswith('#'):
            continue
        if u in seen:
            continue
        seen.add(u)
        targets.append((m.get('id'), m.get('name') or '', u))
    return targets


def _live_tree(sess):
    """读**活的** website.menu —— 渲染导航的同一张表（t85 换源的核心）。"""
    return A.kw(sess, 'website.menu', 'search_read', [[], FIELDS], {'order': 'id'}) or []


def _read_fixture(path):
    with open(path, encoding='utf-8') as fh:
        obj = json.load(fh)
    if not isinstance(obj, list):
        raise ValueError('注入夹具必须是 JSON 数组，实际是 %s' % type(obj).__name__)
    return obj


def login_once():
    """登录**一次**（旧版在每条目标的循环里各登一次：失败会被放大成 N 行 'login-fail'）。
    登录是否成功**只决定"登录态"这一列可不可信** —— 见文件末尾的退出码 2 分支。"""
    try:
        sess, uid, err = A.login(ADMIN_LOGIN, ADMIN_PASSWORD)
        return sess, uid, err
    except Exception as exc:                 # 站点连不上/超时：登记未验证，不伪装成"不可达"
        return None, None, '%s: %s' % (type(exc).__name__, str(exc)[:120])


def resolve_input(sess, uid, err):
    """返回 (tree, source, unverified)。

    · EDU_NAV_TREE 有值 ⇒ 注入夹具（自证模式），**不读活表**；
    · 否则 ⇒ 活表。**不回落快照**：读不到就 unverified，由退出码 2 显式登记。
    """
    inject = os.environ.get('EDU_NAV_TREE')
    if inject:
        print('⚠ 自证模式（EDU_NAV_TREE=%s）：输入是**注入夹具**，不是站点状态 ——' % inject)
        print('   本轮的判据只证"量具会不会红/绿/未验证"，**不代表站点好坏**。')
        print()
        if not os.path.exists(inject):
            return [], 'inject:' + inject, 'EDU_NAV_TREE 指向的文件不存在：%s' % inject
        try:
            return _read_fixture(inject), 'inject:' + inject, None
        except Exception as exc:
            return [], 'inject:' + inject, 'EDU_NAV_TREE 夹具读不出来：%s: %s' % (type(exc).__name__, exc)
    if not uid:
        return [], 'live', '活表 website.menu 读不到（未登录）：%s' % err
    try:
        tree = _live_tree(sess)
    except Exception as exc:
        return [], 'live', '活表 website.menu 读不出来：%s: %s' % (type(exc).__name__, str(exc)[:200])
    if not tree:
        return [], 'live', '活表 website.menu 读到 0 行'
    return tree, 'live', None


def probe(sess, u):
    """一次目标探测：先直接请求，再跟随一次跳转。返回 (展示文本, c1, c2, 错误)。
    错误（连接失败等）**不是**"不可达" —— 记"未验证"，由调用方按未验证处理。"""
    try:
        c1 = A.get(sess, u)[0]
        c2 = A.get(sess, u, follow=True)[0]
        return '%s→%s' % (c1, c2), c1, c2, None
    except Exception as exc:
        return 'ERR(%s)' % type(exc).__name__, None, None, '%s: %s' % (type(exc).__name__, str(exc)[:80])


def main():
    sess, uid, err = login_once()
    tree, source, unverified = resolve_input(sess, uid, err)

    # 输入来源必须**显式登记**：复核者要能一眼看出这次读的是活表还是注入夹具。
    if source == 'live':
        if unverified:
            # 读不到就**不**声称读到了多少行（否则"0 行"会被误读成"导航是空的"）。
            print('输入源：**活的** website.menu（JSON-RPC search_read）—— 本轮**读不到**，详见下方 UNVERIFIED。')
        else:
            print('输入源：**活的** website.menu（JSON-RPC search_read；%d 行；model/字段/排序与 '
                  'scripts/fix_nav_duplicates.py 的 dump_tree() 同口径）' % len(tree))
            print('       历史快照 docs/audit/menu-consolidation/nav-tree-after.json 本轮**未使用**：')
            print('       它是 2026-09-17 的实测快照（不是规格），拿它当输入会红在假问题上（t85）。')
    else:
        print('输入源：**注入夹具** %s（%d 行）—— 自证模式，不代表站点状态' % (source, len(tree)))
    print()

    if unverified:
        print('UNVERIFIED | 输入源给不出可核对的目标：%s' % unverified)
        print('             结论：本轮**不判通过、也不判失败**（退出码 2）。')
        print('             ——凭据可用 EDU_ADMIN_PASSWORD 覆盖（口令不会被打印）；站点探活见 '
              'tests/audit/audit_lib.py 的 BASE。')
        return 2

    targets = _targets(tree)
    if not targets:
        print('UNVERIFIED | 输入源 %s 里**一条可核对目标都没有**（去掉 "#"、"/" 与重复后为 0 条）。'
              % source)
        print('             空输入不判通过 —— 旧版对"文件缺失"会静默给出 0 条并 PASS，那正是假的绿。')
        return 2

    fail, anon_fail, probe_err = [], [], []
    print('导航目标去重后 %d 条（游客态 + 登录态各请求一次；跳转型会跟随一次）' % len(targets))
    print('%-4s %-16s %-22s %-14s %-14s %s' % ('id', '菜单名', 'url', '游客态', '登录态', '判定'))
    for mid, name, u in targets:
        col, dead = [], []          # dead = **已确认**不可达的列（"没看成"不进这里）
        for label in ('anon', 'user'):
            if label == 'user' and not uid:
                # 登录态**未验证**（不是"不可达"）：这一行不给任何可达性结论，
                # 由文件末尾按退出码 2 显式登记。
                col.append('未验证(登录失败)')
                continue
            sess_col = A.sess() if label == 'anon' else sess
            text, c1, c2, perr = probe(sess_col, u)
            col.append(text)
            if perr:
                probe_err.append((mid, name, u, label, perr))
                continue
            if not ((c1 == 200) or (c1 in (302, 303) and c2 == 200 and u in ALLOW_REDIRECT)):
                dead.append(label)
        mark = '❌' if dead else ('⚠' if ('未验证(登录失败)' in col or any('ERR(' in c for c in col)) else '')
        if dead:
            # ⚠ 修 bug（t81 实测）：原来是 fail.append((mid, name, u, rows)) 却按 5 个字段打印，
            #    ⇒ **一有失败就 IndexError**，明细与汇总结论全部打不出来。
            fail.append((mid, name, u, col[0], col[1]))
            if 'anon' in dead:      # 游客态就不可达 ⇒ 与凭据无关的真问题
                anon_fail.append((mid, name, u, col[0]))
        print('%-4s %-16s %-22s %-14s %-14s %s' % (mid, name[:16], u[:22], col[0][:12], col[1][:12], mark))
    print()

    if ALLOW_REDIRECT:
        print('已知设计性跳转（不算失败，但在此登记以便复核）：')
        for k, v in ALLOW_REDIRECT.items():
            print('   %-14s %s' % (k, v))
        print()

    login_unverified = not uid
    if login_unverified:
        print('UNVERIFIED | 登录态这一列**整列未验证**（既不是可达、也不是不可达）：%s' % err)
        print('             login=%s —— 口令用 EDU_ADMIN_PASSWORD 覆盖（口令不会被打印）'
              % ADMIN_LOGIN)
        print()
    if probe_err:
        print('UNVERIFIED | %d 次请求**打不到站点**（既不是可达、也不是不可达），样例：'
              % len(probe_err))
        for mid, name, u, label, perr in probe_err[:5]:
            print('   %s(%s) url=%s [%s 列] %s' % (name[:16], mid, u, label, perr))
        print()

    if fail:
        for f in fail:
            print('FAIL | 菜单 %s(%s) url=%s 游客=%s 登录=%s' % (f[1], f[0], f[2], f[3], f[4]))
        if anon_fail:
            # 退出码优先级与同族门禁一致（check_odoo_trace.py）：**命中(1) > 未验证(2)** ——
            # "已经确认的不可达"比"登录态这次没看成"更强，不能被未验证吞掉。
            print('FAIL | %d/%d 条目标非 200；其中 **%d 条游客态就已确认不可达**（与凭据无关，'
                  '是真问题）：%s' % (len(fail), len(targets), len(anon_fail),
                                    ', '.join(f[2] for f in anon_fail)))
            if login_unverified:
                print('       另有**登录态一列整列未验证**（%s）—— 先修凭据/探活，'
                      '但上面那几条不受影响。' % err)
            return 1
        if login_unverified:
            print('FAIL | %d/%d 条目标非 200 —— **全部落在登录态一列，而该列整列未验证**：'
                  '先修凭据/探活，这些**不是**"导航真的坏了"' % (len(fail), len(targets)))
            return 2
        print('FAIL | %d/%d 条目标非 200' % (len(fail), len(targets)))
        return 1
    if login_unverified:
        print('UNVERIFIED | 游客态 %d 条全部可达，但**登录态这一列没看成**（登录失败 login=%s）。'
              % (len(targets), ADMIN_LOGIN))
        print('             结论：本轮**不判通过**（退出码 2）—— "没看成"≠"没问题"。')
        return 2
    if probe_err:
        print('UNVERIFIED | 无"已确认不可达"的目标，但有 %d 次请求打不到站点（未验证）。'
              % len(probe_err))
        print('             结论：本轮**不判通过**（退出码 2）。')
        return 2
    print('PASS | %d 条导航目标全部 200（游客态 + 登录态，两列均已验证）' % len(targets))
    return 0


# --------------------------------------------------------------------------------------
# 正反双向自证（t85）：**先证量具，再读数**。selftest 不过 ⇒ 本轮任何读数一律不采信。
# --------------------------------------------------------------------------------------
SELFTEST_DEAD = [
    # t10 收口时在册、如今模块已卸载 ⇒ 真会 404 的**真实历史 url**（拿来当"已知不可达"的量具）
    {'id': 9001, 'name': '【自证】slides 历史入口', 'url': '/slides'},
    {'id': 9002, 'name': '【自证】event 历史入口', 'url': '/event'},
    {'id': 9003, 'name': '【自证】forum 历史入口', 'url': '/forum'},
    {'id': 9004, 'name': '【自证】blog 历史入口', 'url': '/blog'},
    {'id': 9005, 'name': '【自证】shop 历史入口', 'url': '/shop'},
    # 合成一条**必然 404** 的目标：不依赖任何模块装没装（防"模块重装后自证跟着失效"）
    {'id': 9006, 'name': '【自证】合成必然 404', 'url': '/__nav_gate_selftest_must_404__'},
]
SELFTEST_HEALTHY = [
    {'id': 9101, 'name': '【自证】学院概况', 'url': '/about'},
    {'id': 9102, 'name': '【自证】课程', 'url': '/courses'},
]
# 故意放一条**请求都发不出去**的 url（不是 404，是压根打不到）：
# 旧版在这里会直接抛栈崩掉；新版必须记"未验证"（rc=2），既不冒充绿、也不冒充红。
SELFTEST_PROBE_ERR = [
    {'id': 9201, 'name': '【自证】打不到的 url', 'url': 'x'},
    {'id': 9202, 'name': '【自证】学院概况', 'url': '/about'},
]
SELFTEST_BAD_CRED = {'EDU_ADMIN_LOGIN': 'nav-gate-selftest-no-such-user',
                     'EDU_ADMIN_PASSWORD': 'nav-gate-selftest-not-a-password'}
# 活的 website.menu 读不出来时用这条假地址（端口 9 = discard，必连不上）。
# 用它而不是"错口令"来证"输入源读不到"：**不消耗**本机 127.0.0.1 的登录失败计数
# （Odoo 的登录冷却按来源 IP 计：res_users._assert_can_auth + base.login_cooldown_after=10）。
SELFTEST_DEAD_SITE = {'AUDIT_BASE': 'http://127.0.0.1:9/'}


def _run_child(env_extra):
    env = dict(os.environ)
    for k in ('EDU_NAV_TREE', 'AUDIT_BASE', 'EDU_ADMIN_LOGIN', 'EDU_ADMIN_PASSWORD'):
        env.pop(k, None)        # 父进程的残留不得漏进子进程（否则"自证"证的是父进程的环境）
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, os.path.abspath(__file__)],
                       capture_output=True, text=True, env=env, timeout=900)
    return p.returncode, p.stdout, p.stderr


def _leg(idx, total, name, env_extra, want, must_have=(), must_not_have=('Traceback',)):
    rc, out, err = _run_child(env_extra)
    blob = out + err
    bad = []
    if rc != want:
        bad.append('rc=%s（期望 %s）' % (rc, want))
    for s in must_have:
        if s not in blob:
            bad.append('输出里找不到 %r' % s)
    for s in must_not_have:
        if s in blob:
            bad.append('输出里出现 %r（崩了 —— "红了但红的原因是崩溃"）' % s)
    print('=' * 88)
    print('SELFTEST leg %d/%d：%s' % (idx, total, name))
    print('  环境注入：%s' % (env_extra or '（无）'))
    print('  期望 rc=%s' % want)
    print('-' * 88)
    print(out.rstrip())
    if err.strip():
        print('-' * 88)
        print('[stderr] ' + err.rstrip())
    print('-' * 88)
    print('  判定：%s（rc=%s%s）' % ('PASS' if not bad else 'FAIL', rc,
                                    '' if not bad else '，' + '；'.join(bad)))
    print()
    return bad


def selftest():
    """正反双向自证：真绿 / 真红 / 优先级 / 未验证（两条路径）/ 收尾。

    leg 1 真绿：活表输入 ⇒ 期望 rc=0（当前站点应当绿）
    leg 2 真红：注入**真会 404** 的目标 ⇒ 期望 rc=1，且明细里读得到 url 与 404（可读明细），
                且**不许崩**（t81 的 IndexError 家族就是"红了但红的原因是崩溃"）
    leg 3 优先级：注入 404 夹具 + 错凭据 ⇒ 期望 rc=1（"已确认不可达"不被"未验证"吞掉）
    leg 4 未验证：注入**健康**夹具 + 错凭据 ⇒ 期望 rc=2 且出现"登录态这一列整列未验证"
    leg 5 未验证：活表输入 + 站点不可达 ⇒ 期望 rc=2（输入源读不到 ⇒ **不判通过**）
    leg 6 未验证：请求**打不到站点**（非 404，是连都连不上）⇒ 期望 rc=2 且不崩
         （旧版在这条路上直接抛栈 —— "既不是红也不是绿"必须显式登记，不能崩、不能冒充）
    leg 7 收尾：错凭据之后仍能正常登录并全绿（确认没把 127.0.0.1 打进 Odoo 登录冷却）
    """
    tmp = tempfile.mkdtemp(prefix='nav-gate-selftest-')
    dead_path = os.path.join(tmp, 'inject-dead.json')
    healthy_path = os.path.join(tmp, 'inject-healthy.json')
    probeerr_path = os.path.join(tmp, 'inject-probe-error.json')
    with open(dead_path, 'w', encoding='utf-8') as fh:
        json.dump(SELFTEST_DEAD, fh, ensure_ascii=False, indent=1)
    with open(healthy_path, 'w', encoding='utf-8') as fh:
        json.dump(SELFTEST_HEALTHY, fh, ensure_ascii=False, indent=1)
    with open(probeerr_path, 'w', encoding='utf-8') as fh:
        json.dump(SELFTEST_PROBE_ERR, fh, ensure_ascii=False, indent=1)

    print('SELFTEST | 导航可达性门禁自身正反双向自证（脚本：%s）' % os.path.abspath(__file__))
    print('         夹具目录：%s' % tmp)
    print()
    legs, total = [], 7

    legs.append(('leg 1 真绿：活表输入，当前站点应当绿',
                 _leg(1, total, '真绿（活表输入）', {}, 0, ('PASS |',))))
    legs.append(('leg 2 真红：注入真会 404 的目标',
                 _leg(2, total, '真红（注入真 404 夹具）', {'EDU_NAV_TREE': dead_path}, 1,
                      ('FAIL |', '/__nav_gate_selftest_must_404__', '404'))))
    legs.append(('leg 3 优先级：命中(1) 不被未验证(2) 吞掉',
                 _leg(3, total, '真红 + 错凭据（优先级）',
                      dict({'EDU_NAV_TREE': dead_path}, **SELFTEST_BAD_CRED), 1,
                      ('FAIL |', '登录态一列整列未验证'))))
    legs.append(('leg 4 未验证：错凭据 ⇒ 登录态整列未验证',
                 _leg(4, total, '未验证（错凭据 + 健康夹具）',
                      dict({'EDU_NAV_TREE': healthy_path}, **SELFTEST_BAD_CRED), 2,
                      ('UNVERIFIED', '登录态这一列'))))
    legs.append(('leg 5 未验证：活表输入读不到 ⇒ 不判通过',
                 _leg(5, total, '未验证（活表输入 + 站点不可达）', dict(SELFTEST_DEAD_SITE), 2,
                      ('UNVERIFIED', '输入源'))))
    legs.append(('leg 6 未验证：请求打不到站点 ⇒ 不冒充红/绿，也不崩',
                 _leg(6, total, '未验证（注入打不到的 url）', {'EDU_NAV_TREE': probeerr_path}, 2,
                      ('UNVERIFIED', '打不到站点'))))
    legs.append(('leg 7 收尾：错凭据之后仍能正常登录并全绿',
                 _leg(7, total, '收尾复验（活表输入）', {}, 0, ('PASS |',))))

    bad = [(n, b) for n, b in legs if b]
    print('=' * 88)
    if bad:
        print('SELFTEST FAIL | %d/%d 腿不达期望：' % (len(bad), total))
        for n, b in bad:
            print('   · %s：%s' % (n, '；'.join(b)))
        print('               ⇒ **量具不可信**，本轮任何读数一律不采信。')
        print('               （此 rc=1 是"自证失败"，不是"导航坏了"。）')
        return 1
    print('SELFTEST PASS | %d/%d 腿全部达期望：真绿(0) / 真红(1) / 优先级(1) / 未验证(2)×3 / 收尾绿(0)'
          % (total, total))
    print('               ⇒ 判据双向成立：绿不假、红不虚、未验证不冒充结论。')
    return 0


if '--selftest' in sys.argv:
    sys.exit(selftest())
if len(sys.argv) > 1:
    sys.stderr.write('用法：python3 scripts/check_nav_reachable.py [--selftest]\n')
    sys.exit(2)
sys.exit(main())
