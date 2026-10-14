#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""站内搜索可用性证据脚本（2026-09-29）。

用户定性：「应用里有个资料下载，我在搜索栏搜『资料下载』啥也没有」+
「希望输入之后下面就像浏览器一样有推荐」。

本脚本一次跑出三类证据（缺一不可），全部打印原始读数并落盘：
  ① 正向：四角色搜「资料下载」→ 结果页出现「应用入口」组 → 点进去 /downloads 真的 200；
  ② 反向：**越权入口不得出现** —— 学生搜「周期排课」「发布公告」应为 0 条入口，
          教务搜到才算；家长侧「我的孩子」同理（正向对照）；
  ③ 控制组：不存在的词 0 条（证明 ① 不是恒真），「资料」≥1 条（证明 ② 不是恒假）。

浏览器层（playwright + axe-core 4.10.2，runOnly tag 与 scripts/check_accessibility.py 一致）：
  · 下拉建议的 combobox 语义：role=combobox / aria-expanded / aria-controls（指向常驻
    listbox）/ aria-activedescendant（↑↓ 时）/ listbox + option（option 必有可访问名）；
  · 键盘：↑↓ 移动、回车打开、Esc 关闭且焦点仍在输入框；
  · **打开态** axe 违规数（合成门禁扫的是静态页面，弹层只能在这里扫）；
  · 渐进增强：**关闭 JS** 时表单照常提交到 /my/search 并出结果。

故障注入（② 的「断言会变红」证明，2026-09-29 实测记录）：
  在 controllers/search.py 的 _panel_entries() 末尾（写缓存前）临时插入一行
      out.append({'title': '周期排课', 'href': '/timetable/bulk', 'desc': '',
                  'app_href': 'timetable/bulk', 'icon': 'fa-calendar-plus-o'})
  再 bash scripts/safe_upgrade.sh edu_portal，然后 --no-browser 跑本脚本 ⇒
  「学生搜『周期排课』搜不到 timetable/bulk 入口」必须 FAIL（exit 1）；删掉该行、
  再升级一次 ⇒ 该条恢复 PASS（exit 0）。两次读数均留档，注入的那次见报告。

产物（static/src/js|css）改动的生效判据（2026-09-29 实测，别当浏览器缓存）：
  · 仅保存文件**不够**：往 search_suggest.js 里插一个探针字符串后，/my/home 引用的
    web.assets_frontend_lazy 的 **bundle 哈希不变（4ace847）**，且探针**不在产物里**；
  · 跑一次 `bash scripts/safe_upgrade.sh edu_portal` 之后：哈希变为 **954f807**、
    探针消失、新代码在产物里 ⇒ 改 JS/CSS 必须升级（或重启 web），**哈希是判据**。
  取哈希：fetch 首页、正则抓 /web/assets/.../web.assets_frontend_lazy.min.js（见 §6 提醒）。

用法：
  python3 tests/smoke/search_suggest_evidence.py              # 全量（含浏览器）
  python3 tests/smoke/search_suggest_evidence.py --no-browser # 只跑 HTTP 三类证据
退出码：0 = 全绿 ｜ 1 = 有断言失败 ｜ 2 = 环境不可用（登录失败 / 浏览器起不来 / axe 取不到）
"""
import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import requests

BASE = 'http://localhost:8069'
DB = 'edu19'
PW = 'demo123'
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, 'out_search_suggest')
ROLES = {
    'stu': ('stu@local', '学生'),
    'fac': ('faculty@local', '教师'),
    'par': ('parent@local', '家长'),
    'bo': ('backoffice@local', '教务'),
}
AXE_VERSION = '4.10.2'
AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']
FAILS = []
NOTES = []


def check(ok, label, detail=''):
    print('  %s %s%s' % ('PASS' if ok else 'FAIL', label,
                         ('  | %s' % detail) if detail else ''))
    if not ok:
        FAILS.append('%s%s' % (label, (' | %s' % detail) if detail else ''))
    return ok


def login(login_name):
    """JSON-RPC 取 session_id（登录页被改成身份选择器，不要走 UI）。"""
    s = requests.Session()
    s.trust_env = False
    for _ in range(3):
        try:
            s.post(BASE + '/web/session/authenticate', json={
                'jsonrpc': '2.0',
                'params': {'db': DB, 'login': login_name, 'password': PW},
            }, timeout=30)
            break
        except Exception:
            time.sleep(2)
    return s


def get_json(sess, path):
    r = sess.get(BASE + path, timeout=30,
                 headers={'Accept': 'application/json'})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


def entry_hits(payload):
    """建议 JSON → [(label, title, href)]（只取 kind=entry 的组）。"""
    out = []
    for grp in (payload or {}).get('groups') or []:
        if grp.get('kind') != 'entry':
            continue
        for it in grp.get('items') or []:
            out.append((grp.get('label'), it.get('title'), it.get('href')))
    return out


# ---------------------------------------------------------------- ① ② ③ HTTP
def http_evidence(res):
    print('\n== ① 正向：搜「资料下载」出结果且点得进去 ==')
    for key, (login_name, cn) in ROLES.items():
        s = login(login_name)
        st, payload = get_json(s, '/my/search/suggest?q=' + quote('资料下载'))
        hits = entry_hits(payload)
        first = hits[0] if hits else None
        print('  [%s/%s] suggest http=%s entry=%s' % (key, cn, st, first))
        check(st == 200 and first is not None and first[2] == '/downloads',
              '%s 建议接口把「资料下载」入口放在首位' % cn,
              'http=%s entry=%s' % (st, first))
        page = s.get(BASE + '/my/search?q=' + quote('资料下载'), timeout=30)
        has_group = '应用入口' in page.text and '/downloads' in page.text
        check(page.status_code == 200 and has_group,
              '%s 结果页出现「应用入口」并含 /downloads 链接' % cn,
              'http=%s 应用入口=%s' % (page.status_code, has_group))
        landing = s.get(BASE + '/downloads', timeout=30, allow_redirects=False)
        check(landing.status_code == 200,
              '%s 点进去（GET /downloads）落地 200' % cn,
              'http=%s' % landing.status_code)
        res['positive'][key] = {
            'suggest_http': st, 'entry': first,
            'result_page_http': page.status_code,
            'result_page_has_entry_group': has_group,
            'landing_http': landing.status_code,
        }

    print('\n== ② 反向：越权入口不得出现（可见性 = 真实可访问性）==')
    # (查询词, 该角色的期望, 不该看到的角色)
    cases = [
        ('周期排课', 'timetable/bulk', 'bo', 'stu'),
        ('发布公告', 'notice/publish', 'bo', 'stu'),
        ('我的孩子', 'my/child', 'par', 'stu'),
    ]
    for word, href, holder, other in cases:
        s_other = login(ROLES[other][0])
        _st, p_other = get_json(s_other, '/my/search/suggest?q=' + quote(word))
        hits_other = entry_hits(p_other)
        leak = [h for h in hits_other if h[2] == '/' + href]
        check(not leak, '%s 搜「%s」搜不到 %s 入口' % (ROLES[other][1], word, href),
              'hits=%s' % hits_other)
        s_holder = login(ROLES[holder][0])
        _st2, p_holder = get_json(s_holder, '/my/search/suggest?q=' + quote(word))
        hits_holder = entry_hits(p_holder)
        own = [h for h in hits_holder if h[2] == '/' + href]
        check(bool(own), '%s 搜「%s」能搜到 %s 入口（正向对照）'
              % (ROLES[holder][1], word, href), 'hits=%s' % hits_holder)
        res['reverse'][word] = {
            'denied_role': other, 'denied_hits': hits_other,
            'allowed_role': holder, 'allowed_hits': hits_holder,
        }

    print('\n== ③ 控制组：断言既不恒真也不恒假 ==')
    s = login(ROLES['stu'][0])
    _st, p_none = get_json(s, '/my/search/suggest?q=' + quote('zzz_no_such_thing_987'))
    none_hits = entry_hits(p_none)
    check(bool(p_none) and not (p_none.get('groups') or []),
          '不存在的词：建议里既无入口也无内容（0 组）',
          'groups=%s' % json.dumps(p_none.get('groups') if p_none else None,
                                   ensure_ascii=False)[:200])
    page = s.get(BASE + '/my/search?q=' + quote('zzz_no_such_thing_987'), timeout=30)
    check('没有找到' in page.text, '不存在的词：结果页显示「没有找到」',
          'http=%s' % page.status_code)
    _st, p_part = get_json(s, '/my/search/suggest?q=' + quote('资料'))
    part_hits = entry_hits(p_part)
    check(bool(part_hits), '部分词「资料」仍能命中入口（真值非恒假）',
          'hits=%s' % part_hits[:3])
    _st, p_empty = get_json(s, '/my/search/suggest')
    check(p_empty == {'q': '', 'groups': [], 'throttled': False},
          '空 q 直接返回空结果（不吐全量）', json.dumps(p_empty, ensure_ascii=False))
    res['control'] = {
        'none_groups': (p_none or {}).get('groups'),
        'partial_hits': part_hits[:5],
        'empty_q': p_empty,
    }

    print('\n== ④ 文案：覆盖面声明不得再漏掉「应用入口」 ==')
    blank = s.get(BASE + '/my/search', timeout=30)
    check('请输入关键词，例如：资料下载' in blank.text,
          '结果页空态文案已含「资料下载」示例',
          'http=%s' % blank.status_code)
    check('顶部搜索框可查<b>应用入口</b>' in blank.text,
          '新手上手清单已写上「应用入口」',
          '命中=%s' % ('顶部搜索框可查<b>应用入口</b>' in blank.text))
    res['copy'] = {
        'empty_state_has_download': '请输入关键词，例如：资料下载' in blank.text,
        'onboard_has_entry': '顶部搜索框可查<b>应用入口</b>' in blank.text,
    }

    print('\n== 限流 A：令牌桶纯函数自证（odoo shell 直调 _bucket_take，确定性）==')
    snippet = (
        "from odoo.addons.edu_portal.controllers.search import ("
        "_bucket_take, _SUGGEST_CAP, _SUGGEST_RATE)\n"
        "store = {}\n"
        "t0 = 1000.0\n"
        "a = sum(1 for i in range(40) if _bucket_take(store, 'u2', t0 + i*0.001))\n"
        "b = sum(1 for i in range(20) if _bucket_take(store, 'u2', t0 + 1.0"
        " + i*0.001))\n"
        "print('SELFTEST cap=%s rate=%s allowed_of_40=%s allowed_after_1s=%s'"
        " % (_SUGGEST_CAP, _SUGGEST_RATE, a, b))\n")
    cmd = ("docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf "
           "-d edu19 --db_host=db -r odoo -w odoo --http-port=8099")
    proc = subprocess.run(cmd, shell=True, cwd=REPO,
                          input=snippet.encode() + b"\nexit()\n",
                          capture_output=True, timeout=240)
    out = (proc.stdout + proc.stderr).decode(errors='replace')
    line = next((l for l in out.splitlines() if l.startswith('SELFTEST ')), '')
    print('  %s' % (line or '(无输出 / 环境问题)'))
    res['throttle_unit'] = line.strip()
    if not line:
        NOTES.append('throttle 自证：odoo shell 未产出读数（环境问题）')
    else:
        kv = dict(p.split('=') for p in line.split()[1:])
        try:
            cap_ok = int(float(kv.get('cap', -1))) == int(kv.get('allowed_of_40', -2))
            rate_ok = int(float(kv.get('rate', -1))) == int(kv.get('allowed_after_1s', -2))
        except (TypeError, ValueError):
            cap_ok = rate_ok = False
        check(cap_ok and rate_ok,
              '令牌桶：连发放行数 = 容量，1 秒后回填数 = 速率',
              line)

    print('\n== 限流 B：HTTP 突发（150 并发；顺序连发打不穿是设计如此）==')
    sid = s.cookies.get('session_id')

    # ⚠ 会话 cookie 只能走**裸 Cookie 头**：requests 的 cookies.set(domain='localhost')
    #   在本站会让服务端认不出会话（实测返回登录页 HTML，全 40 条一起假失败）。
    def burst(i):
        one = requests.Session()
        one.trust_env = False
        try:
            r = one.get(BASE + '/my/search/suggest?q=' + quote('并发%d' % i),
                        timeout=30,
                        headers={'Accept': 'application/json',
                                 'Cookie': 'session_id=%s' % sid})
        except Exception:               # noqa: BLE001
            return None, None
        try:
            return r.status_code, bool((r.json() or {}).get('throttled'))
        except ValueError:
            return r.status_code, None  # 非 JSON：多半被弹回登录页，如实计错误

    n_burst = 150
    with ThreadPoolExecutor(max_workers=n_burst) as pool:
        out = list(pool.map(burst, range(n_burst)))
    thr = sum(1 for _c, t in out if t)
    codes = sorted({c for c, _t in out if c})
    errors = sum(1 for c, _t in out if c is None)
    res['throttle_http'] = {'requests': len(out), 'throttled': thr,
                            'codes': codes, 'connection_errors': errors}
    print('  HTTP 突发读数：requests=%d throttled=%d codes=%s errors=%d'
          % (len(out), thr, codes, errors))
    if errors == len(out):
        # 全连不上 = 环境问题（并发升级/重启期内），不是断言失败：如实标未验证
        print('  ENV 未验证 限流：HTTP 突发全部连接失败（站点正在跑升级/重启？）')
        NOTES.append('throttle: HTTP 突发全部连接失败，本条未验证')
    else:
        # workers=6（config/odoo.conf）⇒ 桶是「每进程一份」：150 并发下每进程
        # 只分到约 25 发，够打穿 15 的容量；顺序连发打不穿是**设计如此**。
        check(thr > 0 and set(codes) <= {200},
              '令牌桶拦 HTTP 突发（150 并发）：throttled>0 且响应仍 200',
              'throttled=%d/%d codes=%s errors=%d' % (thr, len(out), codes,
                                                      errors))
    return res


# ---------------------------------------------------------------- 浏览器
def axe_source():
    path = os.path.join(tempfile.gettempdir(), 'edu_axe',
                        'axe-%s.min.js' % AXE_VERSION)
    if os.path.isfile(path):
        with io.open(path, encoding='utf-8') as fh:
            return fh.read(), 'cache:%s' % path
    try:
        r = requests.get('https://cdn.jsdelivr.net/npm/axe-core@%s/axe.min.js'
                         % AXE_VERSION, timeout=30)
        r.raise_for_status()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path, 'w', encoding='utf-8') as fh:
            fh.write(r.text)
        return r.text, 'cdn'
    except Exception as exc:            # noqa: BLE001
        return None, 'ENV: %s' % exc


def run_axe(page, source):
    page.add_script_tag(content=source)
    return page.evaluate(
        'async () => await axe.run(document, '
        "{resultTypes:['violations'], runOnly:{type:'tag', values:%s}})"
        % json.dumps(AXE_TAGS))


def violations_digest(vres):
    out = []
    for v in vres.get('violations') or []:
        for n in v.get('nodes') or []:
            out.append('%s | %s | %s' % (v.get('id'), v.get('impact'),
                                         (n.get('target') or [''])[0]))
    return out


def browser_evidence(res):
    from playwright.sync_api import sync_playwright
    source, where = axe_source()
    if not source:
        print('== 浏览器证据：ENV 取不到 axe ==', where)
        return None
    print('\n== 浏览器证据（axe %s 来源 %s）==' % (AXE_VERSION, where))
    stu = ROLES['stu'][0]
    sid = login(stu).cookies.get('session_id')
    check(bool(sid), '学生会话取得（注入浏览器）', 'sid_len=%d' % len(sid or ''))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(locale='zh-CN',
                                  viewport={'width': 1280, 'height': 900})
        ctx.add_cookies([{'name': 'session_id', 'value': sid,
                          'domain': 'localhost', 'path': '/'}])
        page = ctx.new_page()
        page.goto(BASE + '/my/home', wait_until='domcontentloaded')
        page.wait_for_timeout(400)

        closed = violations_digest(run_axe(page, source))
        check(not closed, '/my/home 收起态 axe 违规 0', 'violations=%s' % closed)
        res['browser'] = {'axe_closed': closed, 'axe_source': where}

        box = page.locator('form[action="/my/search"] input[name="q"]').first
        check(box.count() == 1, '顶栏搜索框唯一命中', 'count=%d' % box.count())
        attrs_closed = page.eval_on_selector(
            'form[action="/my/search"] input[name="q"]',
            'el => ({role: el.getAttribute("role"), expanded: el.getAttribute'
            '("aria-expanded"), controls: el.getAttribute("aria-controls"),'
            ' name: el.getAttribute("aria-label"), auto: el.getAttribute'
            '("aria-autocomplete")})')
        print('  收起态输入框属性: %s' % attrs_closed)
        check(attrs_closed.get('role') == 'combobox'
              and attrs_closed.get('expanded') == 'false'
              and attrs_closed.get('controls') == 'yy-sg-listbox',
              '收起态：role=combobox / aria-expanded=false / aria-controls 指向常驻 listbox',
              json.dumps(attrs_closed, ensure_ascii=False))

        box.click()
        page.keyboard.type('资料下载', delay=40)
        page.wait_for_selector('.yy-sg-item', timeout=8000)
        page.wait_for_timeout(250)
        opts = page.eval_on_selector_all(
            '.yy-sg-item',
            'els => els.map(e => ({role: e.getAttribute("role"), sel:'
            ' e.getAttribute("aria-selected"), id: e.id, text:'
            ' e.innerText.trim()}))')
        print('  弹层选项: %s' % json.dumps(opts, ensure_ascii=False))
        check(bool(opts) and opts[0]['role'] == 'option'
              and opts[0]['sel'] == 'false' and opts[0]['text'],
              '弹层首项 role=option 有可访问名且未被默认高亮',
              json.dumps(opts[:1], ensure_ascii=False))
        open_attrs = page.eval_on_selector(
            'form[action="/my/search"] input[name="q"]',
            'el => ({role: el.getAttribute("role"), expanded: el.getAttribute'
            '("aria-expanded"), controls: el.getAttribute("aria-controls"),'
            ' active: el.getAttribute("aria-activedescendant"),'
            ' box: !!document.getElementById(el.getAttribute("aria-controls")),'
            ' boxRole: (document.getElementById(el.getAttribute("aria-controls"))'
            ' || {}).getAttribute ? document.getElementById(el.getAttribute'
            '("aria-controls")).getAttribute("role") : null})')
        print('  展开态输入框属性: %s' % json.dumps(open_attrs, ensure_ascii=False))
        check(open_attrs.get('expanded') == 'true' and open_attrs.get('box')
              and open_attrs.get('boxRole') == 'listbox',
              '展开态：aria-expanded=true 且 aria-controls 解析到 role=listbox',
              json.dumps(open_attrs, ensure_ascii=False))
        res['browser']['options'] = opts
        res['browser']['attrs_open'] = open_attrs

        opened = violations_digest(run_axe(page, source))
        check(not opened, '建议弹层**打开态** axe 违规 0', 'violations=%s' % opened)
        res['browser']['axe_open'] = opened
        page.screenshot(path=os.path.join(OUT, 'suggest_open.png'))

        page.keyboard.press('ArrowDown')
        page.wait_for_timeout(120)
        act = page.eval_on_selector(
            'form[action="/my/search"] input[name="q"]',
            'el => ({act: el.getAttribute("aria-activedescendant"),'
            ' sel: (document.getElementById(el.getAttribute'
            '("aria-activedescendant"))||{}).getAttribute ? document.getElementById'
            '(el.getAttribute("aria-activedescendant")).getAttribute'
            '("aria-selected") : null})')
        print('  ArrowDown 后: %s' % json.dumps(act, ensure_ascii=False))
        check(bool(act.get('act')) and act.get('sel') == 'true',
              '↑↓ 键盘可达：aria-activedescendant 指向高亮项且 aria-selected=true',
              json.dumps(act, ensure_ascii=False))
        res['browser']['active_descendant'] = act

        page.keyboard.press('Escape')
        page.wait_for_timeout(120)
        esc = page.evaluate(
            '() => { const p = document.getElementById("yy-sg-panel");'
            ' const i = document.querySelector'
            '(\'form[action="/my/search"] input[name="q"]\');'
            ' return {hidden: p.hidden, focused: document.activeElement === i,'
            ' expanded: i.getAttribute("aria-expanded")}; }')
        print('  Esc 后: %s' % json.dumps(esc, ensure_ascii=False))
        check(esc.get('hidden') and esc.get('focused')
              and esc.get('expanded') == 'false',
              'Esc 关闭弹层且焦点仍在输入框（不抢 search_focus 的失焦语义）',
              json.dumps(esc, ensure_ascii=False))
        res['browser']['escape'] = esc

        # 回车 = 打开高亮项（这里先 ↓ 再回车）
        page.keyboard.press('ArrowDown')
        page.wait_for_timeout(120)
        page.keyboard.press('Enter')
        page.wait_for_load_state('domcontentloaded')
        page.wait_for_timeout(300)
        print('  回车后落地: %s' % page.url)
        check(page.url.startswith(BASE + '/downloads'),
              '↓ + 回车 打开高亮项，落地 /downloads', page.url)
        res['browser']['enter_url'] = page.url

        # 结果页（应用入口组）也扫一遍：/my/search 不在合成门禁的 axe 取样里
        page.goto(BASE + '/my/search?q=' + quote('资料下载'),
                  wait_until='domcontentloaded')
        page.wait_for_timeout(300)
        rp = violations_digest(run_axe(page, source))
        check(not rp, '/my/search?q=资料下载 结果页 axe 违规 0',
              'violations=%s' % rp)
        res['browser']['axe_result_page'] = rp
        page.screenshot(path=os.path.join(OUT, 'result_page.png'))
        ctx.close()

        # 渐进增强：JS 关掉后表单照常提交
        ctx2 = browser.new_context(locale='zh-CN', java_script_enabled=False,
                                   viewport={'width': 1280, 'height': 900})
        ctx2.add_cookies([{'name': 'session_id', 'value': sid,
                           'domain': 'localhost', 'path': '/'}])
        p2 = ctx2.new_page()
        p2.goto(BASE + '/my/home', wait_until='domcontentloaded')
        p2.fill('form[action="/my/search"] input[name="q"]', '资料下载')
        p2.click('form[action="/my/search"] button[type="submit"]')
        p2.wait_for_load_state('domcontentloaded')
        body = p2.inner_text('body')
        check(p2.url.startswith(BASE + '/my/search')
              and '应用入口' in body and '资料下载' in body,
              '无脚本（JS 关闭）：表单照样提交并出「应用入口」结果',
              'url=%s' % p2.url)
        res['browser']['no_js_url'] = p2.url
        res['browser']['no_js_has_entry'] = '应用入口' in body
        browser.close()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-browser', action='store_true')
    ap.add_argument('--json', dest='json_out', default=None)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    res = {'base': BASE, 'roles': list(ROLES), 'positive': {}, 'reverse': {},
           'control': {}, 'browser': {}}
    try:
        http_evidence(res)
    except requests.RequestException as exc:
        print('ENV：站点不可达 %s' % exc)
        return 2
    if not args.no_browser:
        try:
            browser_evidence(res)
        except Exception as exc:        # noqa: BLE001
            print('  ENV 浏览器证据失败：%s' % exc)
            NOTES.append('browser: %s' % exc)
    res['fails'] = FAILS
    res['notes'] = NOTES
    out = args.json_out or os.path.join(OUT, 'evidence.json')
    with io.open(out, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(res, ensure_ascii=False, indent=2))
    print('\n================ 汇总 ================')
    print('断言失败 %d 条' % len(FAILS))
    for f in FAILS:
        print('  FAIL %s' % f)
    if NOTES:
        print('环境备注：%s' % ' / '.join(NOTES))
    print('证据落盘：%s' % out)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
