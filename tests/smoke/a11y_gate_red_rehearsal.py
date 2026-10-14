#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""无障碍门禁「注入违例 ⇒ 必须变红 ⇒ 复原」演练器（2026-09-29）。

## 为什么要有这个文件

2026-09-29 补了两处门禁覆盖（scripts/check_accessibility.py 的 AUDIT_ROUTES）：

  · `/registrar/curriculum`（教务天天用的课程编排页）—— 原先在 tests/ui/surface.json 里
    gates=[] / status=gap，**三张 UI 门禁没有一张扫它**；
  · `/assess` 与 `/assess/review` 的**教务 / 教师取样身份** —— 原先只有 student（/assess）、
    faculty（/assess/review），而「整班打分」卡片挂在 can_grade = 教务组·系统组 ∪ 教师组上
    ⇒ **那张卡的渲染路径结构上不可能被学生身份扫到**。

「登记进名单」≠「真的会被扫到」，「扫到且 0 违规」≠「这把尺子在这页上量得动缺陷」。
两件事都必须被证明，否则新增的覆盖可能只是**假绿**（本仓刚因为一条 carve-out
让一个紫胶囊活了几个月）。本文件证明第二件：**注入一个违例 ⇒ 门禁必须变红 ⇒ 复原后必须回绿**。

## 注入手法（**不改仓库任何文件、不跑 `-u` 升级**）

在 odoo shell 里**运行时**建一条 `ir.ui.view`（无 xmlid 的临时继承视图），用 xpath 把违例元素
插进目标页面模板的指定锚点；测完 `unlink` 掉，并**逐字复核库里已无残留**。

为什么不用「改模块 XML + `safe_upgrade.sh`」（UX_V3_GATE.md §11.3 对后台页用的那套）：
  · `-u edu_portal` 会重放被 edu_nav 收口的菜单（已登记的未关闭风险 **F1**，
    `docs/audit/finding-F1-menu-replay-on-upgrade.md`）⇒ 会**顺手改掉别的 agent 正在依赖的状态**；
  · 静态资源本来就只需重载，而模板继承走 ORM 会**立刻**对下一次 HTTP 请求生效（ir.ui.view 自清缓存），
    不需要重启、不需要升级锁。
  · 本演练**只动本地 edu19 库的一条临时视图记录**，建完即删，全程可见于下方读数。

## 注入什么

每个目标一次插入**两**个独立违例（互为配对，避免单条规则在某些浏览器/版本上不触发）：

  ① `<img>` 无 `alt`            → axe 规则 `image-alt`（critical）
  ② `<button>` 里面只有一个空 `<span>` → axe 规则 `button-name`（critical）

判定不写死用哪一条：**断言「本页的规则集合相对基线出现了注入前没有的新规则」**，
并把**实际命中的规则 id** 原样打印/落盘 —— 尺子量到哪一条就说哪一条，不替它挑。

## 跑法

    python3 tests/smoke/a11y_gate_red_rehearsal.py                 # 两个目标都跑
    python3 tests/smoke/a11y_gate_red_rehearsal.py --target curriculum
    python3 tests/smoke/a11y_gate_red_rehearsal.py --target assess
    python3 tests/smoke/a11y_gate_red_rehearsal.py --json 结果.json  # 默认写同目录 _results.json

## 退出码

0 = 全部通过（两个方向都成立）｜1 = **判据失败**（注入后没变红 / 复原后没回绿 / 有残留）
｜2 = ENV（升级锁在 / 站点不可达 / axe 取不到 / 浏览器起不来 / odoo shell 不可用）—— ENV 不当通过。

## 自清

`try/finally`：无论断言是否失败、乃至中途异常，临时视图都会被删；`--restore` 可单独执行清场。
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RESULTS = HERE / 'a11y_gate_red_rehearsal_results.json'
GATE = REPO / 'scripts' / 'check_accessibility.py'
LOCK = Path(os.environ.get('TMPDIR') or '/tmp') / 'edu19_upgrade.lock'
MARK = 'A11Y-GATE-REHEARSAL-'

#: 每个目标：门禁取样路径 + 受影响的取样身份 + 要继承的模板 + xpath 锚点
#: ⚠ 锚点写的是**模板 arch 里真实存在的属性**（继承发生在 arch 层，渲染前），不是渲染结果。
TARGETS = {
    'curriculum': {
        'path': '/registrar/curriculum',
        'gate_paths': ['/registrar/curriculum'],
        'roles_expected_red': ['backoffice'],
        'roles_expected_clean': [],
        'inherit_xmlid': 'edu_portal.edu_registrar_curriculum',
        'xpath': "//h4[hasclass('mb-0')]",
        'position': 'inside',
        'why': '教务课程编排页 —— 本轮新登记进 surface.json（原 gates=[] / status=gap）',
    },
    'assess': {
        'path': '/assess',
        'gate_paths': ['/assess', '/assess/review'],
        'roles_expected_red': ['backoffice', 'faculty'],
        'roles_expected_clean': ['student'],
        'inherit_xmlid': 'edu_assess.edu_assess_home',
        # 「整班打分」卡片本体：<div class="col" t-if="can_grade">
        'xpath': "//div[@t-if='can_grade']",
        'position': 'inside',
        'why': '「整班打分」卡片 —— 本轮新补的教务/教师取样身份；学生身份结构上看不到它',
    },
}

#: 注入的违例元素（**两个独立违例配对**，避免单条规则在某个浏览器/版本上不触发就误判"量不到"）
#:   ① <img> 无 alt          → axe image-alt（critical）
#:   ② <button> 里只有空 <span> → axe button-name（critical）
#: 判据不挑了用哪一条：只断言「本页出现了注入前没有的新规则」，并把实际命中的规则 id 原样落盘。
VIOLATING_XML = ('<img src="/web/static/img/placeholder.png" width="32" height="32"/>'
                 '<button type="button" class="btn btn-sm btn-light ms-1">'
                 '<span></span></button>')

OK, FAIL = 'PASS', 'FAIL'
items, readings = [], {}


def check(name, cond, detail=''):
    items.append({'name': name, 'pass': bool(cond), 'detail': str(detail)[:2000]})
    print('  %-4s | %-64s | %s' % (OK if cond else FAIL, name, str(detail)[:300]))
    return bool(cond)


def note(msg):
    print('  ---- %s' % msg)


def die(msg, code=2):
    print('ENV: %s' % msg)
    json.dump({'error': msg, 'items': items, 'readings': readings,
               'when': datetime.datetime.now().isoformat()},
              open(RESULTS, 'w'), ensure_ascii=False, indent=1)
    return code


# ---------------------------------------------------------------------- odoo shell

SHELL_CMD = ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
             '-c', '/etc/odoo/odoo.conf', '-d', 'edu19',
             '--db_host=db', '-r', 'odoo', '-w', 'odoo', '--no-http']


def odoo_shell(body, timeout=180):
    """在 odoo shell（stdin）里跑一段代码 → (stdout, err)。

    ⚠ odoo shell 退出时会回滚 ⇒ 要落库的写入必须在脚本里显式 commit（本文件照做）。
    """
    try:
        p = subprocess.run(SHELL_CMD, input=body, capture_output=True, text=True,
                           cwd=str(REPO), timeout=timeout)
    except Exception as exc:                                   # noqa: BLE001
        return '', 'odoo shell 起不来：%s' % str(exc)[:160]
    out = (p.stdout or '') + (p.stderr or '')
    return out, ''


def inject_view(target, live_dom):
    """建临时继承视图 → (view_id, out)。失败 view_id = None。"""
    xmlid = TARGETS[target]['inherit_xmlid']
    xpath = TARGETS[target]['xpath']
    position = TARGETS[target]['position']
    name = MARK + target
    arch = "<data><xpath expr=%r position=%r>%s</xpath></data>" % (
        xpath, position, VIOLATING_XML)
    body = ("V = env['ir.ui.view'].sudo()\n"
            "name = %r\n"
            "V.search([('name', '=', name)]).unlink()\n"          # 幂等：先清同名残留
            "parent = env.ref(%r)\n"
            "vid = V.create({'name': name, 'type': 'qweb', 'mode': 'extension',\n"
            "                'inherit_id': parent.id, 'arch_db': %r,\n"
            "                'active': True, 'priority': 99})\n"
            "env.cr.commit()\n"
            "\n"
            "# ⚠⚠ 关键一步，缺了它本演练会得到**自相矛盾**的读数（本文件首版实测踩到）：\n"
            "#   本栈 odoo 是 workers=6（config/odoo.conf）⇒ 6 个 worker 各自持有自己的\n"
            "#   registry/模板缓存。而跨进程失效**不是**靠数据库触发器，是靠\n"
            "#   odoo/orm/registry.py 的 signal_changes() 往 orm_signaling_<cache> 插一行；\n"
            "#   而 signal_changes() 只在 **RPC 分发**结束处被调用（odoo/service/model.py 的\n"
            "#   dispatch）。odoo shell 走的是直接 ORM + cr.commit()，**从不经过 dispatch**\n"
            "#   ⇒ 别的 worker 永远收不到通知，只能靠 ormcache 的 LRU 随机淘汰偶尔看到新 arch。\n"
            "#   实测形态（本文件首版）：同一页 36 次请求的命中序列是 T/F 交错且 150 秒不收敛\n"
            "#   —— 那不是「身份判据不成立」，是量具没把变更送出去。\n"
            "#   修法 = 改完显式 signal_changes() 一次。\n"
            "env.registry.signal_changes()\n"
            "print('INJECTED_VIEW_ID', vid.id)\n" % (name, xmlid, arch))
    out, err = odoo_shell(body)
    if err:
        return None, err
    vid = None
    for line in out.splitlines():
        if line.startswith('INJECTED_VIEW_ID'):
            vid = int(line.split()[-1])
    print('    [inject] %s | 模板 %s | xpath %s | view_id=%s'
          % (target, xmlid, xpath, vid))
    if vid is None:
        return None, '注入失败（未拿到 view id）：%s' % out[-600:]
    return vid, out


def restore_view(target, keep=False):
    """删临时视图并**逐字复核残留 = 0** → (残留条数, out)。"""
    name = MARK + target
    body = ("V = env['ir.ui.view'].sudo()\n"
            "rec = V.search([('name', '=', %r)])\n"
            "print('BEFORE_UNLINK', len(rec))\n"
            "rec.unlink()\n"
            "env.cr.commit()\n"
            "env.registry.signal_changes()\n"      # 同 inject：不喊这一声，6 个 worker 收不到
            "print('AFTER_UNLINK', len(V.search([('name', '=', %r)])))\n"
            "print('TOTAL_MARK_LEFT', V.search_count([('name', 'like', %r)]))\n"
            % (name, name, MARK + '%'))
    out, err = odoo_shell(body)
    if err:
        return None, err
    after = total = None
    for line in out.splitlines():
        if line.startswith('AFTER_UNLINK'):
            after = int(line.split()[-1])
        if line.startswith('TOTAL_MARK_LEFT'):
            total = int(line.split()[-1])
    return total if total is not None else after, out


def restore_all():
    body = ("V = env['ir.ui.view'].sudo()\n"
            "rec = V.search([('name', 'like', %r)])\n"
            "print('FOUND', len(rec), rec.mapped('name'))\n"
            "rec.unlink()\n"
            "env.cr.commit()\n"
            "env.registry.signal_changes()\n"
            "print('LEFT', V.search_count([('name', 'like', %r)]))\n"
            % (MARK + '%', MARK + '%'))
    return odoo_shell(body)


# ---------------------------------------------------------------------- 门禁

def run_gate(path, tag):
    """跑门禁定向重扫 → (exit_code, json_dict, 原始 stdout)。"""
    out_json = Path(os.environ.get('TMPDIR') or '/tmp') / ('a11y_rehearsal_%s.json' % tag)
    if out_json.exists():
        out_json.unlink()
    cmd = [sys.executable, str(GATE), '--only', path, '--json', str(out_json)]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO), timeout=900)
    doc = None
    if out_json.exists():
        try:
            doc = json.load(open(out_json, encoding='utf-8'))
        except Exception:                                      # noqa: BLE001
            doc = None
    return p.returncode, doc, (p.stdout or '') + (p.stderr or '')


def page_rules(doc):
    """{ 'role path': [rule_id, ...] } —— 只取本页**判据**（门户页= axe 全量；后台页= gated）。"""
    out = {}
    for r in (doc or {}).get('pages') or []:
        out['%s %s' % (r.get('role'), r.get('path'))] = sorted(
            x.get('id') for x in (r.get('rules') or []))
    return out


# ---------------------------------------------------------------------- 视图缓存「等稳定」
# ⚠ 实测踩到的坑（2026-09-29，本脚本首版就中）：临时视图是在**另一个进程**（odoo shell）里
#    建/删的，而 web 进程的 qweb 模板缓存不是立刻失效 —— 首版读数出现过这种自相矛盾的形态：
#    注入后 backoffice /assess 已报 button-name，紧挨着的 faculty /assess 却报 0；
#    复原后反过来，faculty /assess 冒出了注入期的规则。
#    那不是「身份判据不成立」，是**缓存还差一个请求**。⇒ 每次改完视图必须**轮询到稳定**再判，
#    否则得到的是「量具没跟上」的假红/假绿（本仓最忌讳的那类结论）。
#    轮询探针用**纯 HTTP + 注入元素的字面标记**，不开浏览器、不跑整轮门禁，几秒钟就能稳定。
MARKER = 'placeholder.png'      # 注入的 <img src> 里的字面标记（页面 HTML 里出现 = 视图生效）


def _sessions():
    """复用门禁脚本自己的登录助手（同一份会话口径，避免两套登录实现漂移）。"""
    sys.path.insert(0, str(REPO / 'scripts'))
    import check_accessibility as G
    out = {}
    for role, (login, pwd) in G.ROLE_LOGINS.items():
        try:
            out[role] = G.login_session(login, pwd)
        except Exception:                                      # noqa: BLE001
            out[role] = None
    return out


#: ⚠⚠ 第二个坑（同一天实测，比第一个更难发现）：**本栈 odoo 是 workers=6**
#:     （config/odoo.conf）。6 个 worker 各自持有自己的 qweb 模板缓存，而 HTTP 是轮询分发的
#:     ⇒ 「改完视图后打两个请求都看到新内容」**不等于**「6 个 worker 都更新了」；
#:     更糟的是 requests.Session 默认 keep-alive，会把同一个连接**钉在同一个 worker** 上，
#:     于是探针自己在给自己报假平安。首版就是这么判出「faculty 没变红」的 —— 其实只是那一个
#:     worker 还没轮到新模板。⇒ 稳定判据必须是：**主动断开连接、连打 N 次、连续 R 轮全部一致**。
CONN = {'Connection': 'close'}     # 关 keep-alive，否则连接被钉死在单个 worker 上
WARM_PER_ROUND = 12                # 每轮请求数（> workers=6，保证每个 worker 都被轮到的概率足够高）
WARM_ROUNDS = 3                    # 连续几轮全部一致才算稳定


def _probe(sess, path):
    """一次不带 keep-alive 的 GET → (marker?, status)。"""
    try:
        r = sess.get('http://localhost:8069' + path, timeout=30,
                     allow_redirects=False, headers=CONN)
        return MARKER in (r.text or ''), r.status_code
    except Exception as exc:                                   # noqa: BLE001
        return 'ERR:%s' % str(exc)[:60], 0


def wait_marker(sess, path, want, timeout=150.0, step=1.0):
    """轮询到「**所有 worker** 上标记的出现/消失都稳定」为止 → (达成?, 末轮读数, 用时秒)。

    达成条件 = 连续 WARM_ROUNDS 轮、每轮 WARM_PER_ROUND 次请求**全部**满足 marker == want。
    """
    t0 = time.time()
    stable, last_round = 0, []
    while time.time() - t0 < timeout:
        last_round = [_probe(sess, path) for _ in range(WARM_PER_ROUND)]
        if all(isinstance(m, bool) and m is want and st == 200 for m, st in last_round):
            stable += 1
            if stable >= WARM_ROUNDS:
                return True, {'rounds': stable, 'n': WARM_PER_ROUND,
                              'sample': last_round[:2]}, round(time.time() - t0, 1)
        else:
            stable = 0
        time.sleep(step)
    return False, {'rounds': stable, 'last': last_round}, round(time.time() - t0, 1)


# ---------------------------------------------------------------------- 单目标演练

def rehearse(target, baseline_doc):
    """返回 True/False（判据是否全部成立）。异常向上抛，由调用方 finally 清场。"""
    t = TARGETS[target]
    path = t['path']
    print('\n== 目标 %s（%s）== ' % (target, path))
    note(t['why'])

    base = page_rules(baseline_doc)
    base_rules = sorted({r for v in base.values() for r in v})
    print('    基线（注入前）逐页规则：%s' % json.dumps(base, ensure_ascii=False))
    readings.setdefault(target, {})['baseline_rule_sets'] = base

    sess = _sessions()
    if not sess.get(t['roles_expected_red'][0]):
        check('%s: 取样身份的登录会话可用' % target, False, '登录失败：%s'
              % t['roles_expected_red'][0])
        return False

    # ---- 0) 注入前**逐身份**先量一次页面本身（不是门禁读数，是「这张卡在谁身上渲染」的直读）----
    pre = {}
    for role in sorted(set(t['roles_expected_red']) | set(t['roles_expected_clean'])):
        hit = [_probe(sess[role], path) for _ in range(WARM_PER_ROUND)]
        pre[role] = {'statuses': sorted({st for _m, st in hit}),
                     'marker_seen': sum(1 for m, _st in hit if m is True),
                     'n': len(hit)}
    readings[target]['pre_page_probe'] = pre
    print('    注入前逐身份直读 %s：%s' % (path, json.dumps(pre, ensure_ascii=False)))
    check('%s: 注入前所有取样身份都能打开本页（非 303 弹走）' % target,
          all(v['statuses'] == [200] for v in pre.values()),
          json.dumps(pre, ensure_ascii=False))

    vid, out = inject_view(target, None)
    if vid is None:
        check('%s: 临时视图注入成功' % target, False, out)
        return False
    check('%s: 临时继承视图已建（ir.ui.view id=%s，无 xmlid，测完即删）' % (target, vid),
          True, 'inherit %s / xpath %s' % (t['inherit_xmlid'], t['xpath']))

    # ---- 1) 等视图生效（跨进程缓存滞后，必须逐身份轮询到稳定）----
    settled = {}
    for role in sorted(set(t['roles_expected_red']) | set(t['roles_expected_clean'])):
        want = role in t['roles_expected_red']
        got, last, secs = wait_marker(sess[role], path, want)
        settled[role] = {'want_marker': want, 'ok': got, 'last': last, 'secs': secs}
    readings[target]['settle_after_inject'] = settled
    print('    等待注入生效（逐身份，最多 60s）：%s' % json.dumps(settled, ensure_ascii=False))
    check('%s: 注入的标记元素已稳定落在**预期身份**上（%s）'
          % (target, '/'.join(t['roles_expected_red'])),
          all(v['ok'] for r, v in settled.items() if r in t['roles_expected_red']),
          json.dumps({r: v for r, v in settled.items() if r in t['roles_expected_red']},
                     ensure_ascii=False))
    if t['roles_expected_clean']:
        check('%s: 对照身份（%s）页面上**始终没有**该元素 —— 证明它本就只在别的身份上渲染'
              % (target, '/'.join(t['roles_expected_clean'])),
              all(v['ok'] for r, v in settled.items() if r in t['roles_expected_clean']),
              json.dumps({r: v for r, v in settled.items() if r in t['roles_expected_clean']},
                         ensure_ascii=False))

    code, doc, raw = run_gate(','.join(t['gate_paths']), 'inject_' + target)
    readings[target]['injected_exit'] = code
    after = page_rules(doc)
    readings[target]['injected_rule_sets'] = after
    print('    注入后 exit=%s｜逐页规则：%s' % (code, json.dumps(after, ensure_ascii=False)))

    # ① 变红：至少一页出现了注入前没有的新规则
    new_per_page = {k: [r for r in v if r not in base.get(k, [])] for k, v in after.items()}
    new_any = {k: v for k, v in new_per_page.items() if v}
    readings[target]['new_rules_per_page'] = new_per_page
    check('%s: 注入后门禁**变红**（exit 非 0）' % target, code != 0,
          'exit=%s；新规则逐页=%s' % (code, json.dumps(new_any, ensure_ascii=False)))
    check('%s: 变红的原因是**本页出现了注入前没有的 axe 规则**' % target,
          bool(new_any), json.dumps(new_any, ensure_ascii=False))
    readings[target]['injected_rules_hit'] = sorted({r for v in new_any.values() for r in v})

    # ② 身份落点：新规则只应出现在预期身份上（这条同时证明「覆盖口径」本身是对的）
    red_roles = sorted({k.split(' ', 1)[0] for k in new_any})
    check('%s: 变红只发生在预期身份上（%s）' % (target, '/'.join(t['roles_expected_red'])),
          set(red_roles) == set(t['roles_expected_red']),
          '实际变红身份=%s｜预期=%s' % (red_roles, t['roles_expected_red']))
    readings[target]['red_roles'] = red_roles

    if t['roles_expected_clean']:
        clean_ok = all(not new_per_page.get('%s %s' % (r, path))
                       for r in t['roles_expected_clean'])
        check('%s: 对照身份（%s）**没有**新规则 —— 证明该元素本就只在另外的身份上渲染'
              % (target, '/'.join(t['roles_expected_clean'])), clean_ok,
              json.dumps({r: new_per_page.get('%s %s' % (r, path)) for r in t['roles_expected_clean']},
                         ensure_ascii=False))

    # ③ 复原 + 逐字复核残留
    leftover, ro = restore_view(target)
    check('%s: 临时视图已删且残留 = 0' % target, leftover == 0, '残留=%s' % leftover)
    readings[target]['leftover_after_restore'] = leftover
    readings[target]['restore_raw'] = [l for l in (ro or '').splitlines()
                                       if l.startswith(('BEFORE_UNLINK', 'AFTER_UNLINK',
                                                        'TOTAL_MARK_LEFT'))]

    # 复原同样要等稳定（否则会量到「上一个请求还没换缓存」的残影）
    back_settle = {}
    for role in sorted(set(t['roles_expected_red']) | set(t['roles_expected_clean'])):
        got, last, secs = wait_marker(sess[role], path, False)
        back_settle[role] = {'ok': got, 'last': last, 'secs': secs}
    readings[target]['settle_after_restore'] = back_settle
    print('    等待复原生效（逐身份，最多 60s）：%s' % json.dumps(back_settle, ensure_ascii=False))
    check('%s: 复原后所有取样身份的页面上都不再有过该元素' % target,
          all(v['ok'] for v in back_settle.values()), json.dumps(back_settle, ensure_ascii=False))

    code2, doc2, _raw2 = run_gate(','.join(t['gate_paths']), 'restored_' + target)
    back = page_rules(doc2)
    readings[target]['restored_exit'] = code2
    readings[target]['restored_rule_sets'] = back
    print('    复原后 exit=%s｜逐页规则：%s' % (code2, json.dumps(back, ensure_ascii=False)))
    check('%s: 复原后门禁**回绿**（exit 0 且逐页规则与基线逐字相同）' % target,
          code2 == 0 and back == base, 'exit=%s｜与基线相同=%s' % (code2, back == base))
    return all(i['pass'] for i in items)


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', default='all',
                    help='curriculum | assess | all（默认 all）')
    ap.add_argument('--json', default=None,
                    help='读数落盘路径（默认 tests/smoke/a11y_gate_red_rehearsal_results.json）')
    ap.add_argument('--restore', action='store_true',
                    help='只清场（删除所有 %s* 临时视图）后退出' % MARK)
    args = ap.parse_args()

    if args.json:
        globals()['RESULTS'] = Path(args.json)

    if args.restore:
        out, _e = restore_all()
        print(out[-800:])
        return 0

    # ---- ENV 前置 ----
    if LOCK.exists():
        return die('升级锁存在（%s）⇒ 有人的 safe_upgrade 在跑，本轮作废' % LOCK)
    if not GATE.is_file():
        return die('门禁脚本不在：%s' % GATE)

    out, err = odoo_shell("print('SHELL_OK', len(env['ir.ui.view'].sudo().search([])))")
    if err or 'SHELL_OK' not in out:
        return die('odoo shell 不可用：%s' % (err or out[-300:]))
    print('odoo shell OK｜%s' % [l for l in out.splitlines() if 'SHELL_OK' in l][:1])

    targets = list(TARGETS) if args.target == 'all' else [args.target]
    for t in targets:
        if t not in TARGETS:
            return die('未知目标 %s（可用：%s）' % (t, '、'.join(TARGETS)))

    # ---- 注入前的基线：逐目标先量一次（也是「真的被扫到」的证据）----
    only = ','.join(sorted({p for t in targets for p in TARGETS[t]['gate_paths']}))
    code, doc, raw = run_gate(only, 'baseline')
    if doc is None:
        return die('基线门禁跑不出 JSON（exit=%s）：%s' % (code, raw[-800:]))
    readings['baseline_exit'] = code
    readings['baseline_pages'] = page_rules(doc)
    print('\n== 注入前基线：%s ==' % only)
    print('  exit=%s｜扫描页=%s' % (code, json.dumps(page_rules(doc), ensure_ascii=False)))
    for k in sorted(page_rules(doc)):
        check('基线：取样身份真的被扫到 —— %s' % k, True, '进入门禁扫描集并成功渲染')
    if code != 0:
        note('⚠ 基线不是 0（扩覆盖扫出了既有违规）—— 演练仍可继续，但'
             '「复原后回绿」的判据要按**基线的实际读数**比，不能按 0 比。')

    failures = []
    try:
        for t in targets:
            try:
                good = rehearse(t, doc)
            except Exception as exc:                           # noqa: BLE001
                check('%s: 演练过程未抛异常' % t, False, repr(exc)[:300])
                good = False
            if not good:
                failures.append(t)
    finally:
        out, _e = restore_all()
        print('\n== 清场（无论成败）==')
        for line in (out or '').splitlines():
            if line.startswith(('FOUND', 'LEFT')):
                print('  %s' % line)

    npass = sum(1 for i in items if i['pass'])
    nfail = len(items) - npass
    print('\n合计：PASS %d / FAIL %d' % (npass, nfail))
    json.dump({'when': datetime.datetime.now().isoformat(), 'targets': targets,
               'items': items, 'readings': readings, 'pass': npass, 'fail': nfail},
              open(RESULTS, 'w'), ensure_ascii=False, indent=1)
    print('读数已写 %s' % RESULTS)
    return 0 if nfail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
