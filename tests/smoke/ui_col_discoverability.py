#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账单列表「列可发现性」正反双向自证（Playwright 真机，before/after 同一把尺子）。

背景
----
用户原话：「它很多功能被折叠了，导致我不点都不知道有这些功能」。
调研（docs/research/ui-usability-discoverability.md §2.3）已查实 Odoo 19 列表列可见性
只有两个开关，语义完全不同：
  · optional="hide"/"show" → 默认隐藏/显示，但**都进「列设置」菜单** ⇒ 有找回路径；
  · column_invisible="<expr>" → **硬隐藏，连列设置菜单都进不去** ⇒ 永久不可发现（D1 缺陷）。
本脚本用真实浏览器读**渲染结果**（不是读 XML），对同一份视图给出可复算的判据：
  ① 默认渲染出哪些 <th>（= 用户不点任何东西就看得见的列）；
  ② 列设置菜单里有哪些勾选项（= 用户能找回哪些列）；
  ③ localStorage 里没有 optional_fields 记录（⇒ ①看到的确实是「默认值」，不是上次留下的偏好）。

为什么不能只看 XML：optional 的默认值由前端 list_renderer.js:1185-1188 决定，
localStorage 有记录时会覆盖默认值 —— 读 XML 证明不了「用户第一次打开看到什么」。

用法（解释器必须写全路径，见 scripts/check_ui_usability.py 同一段口径）
    /opt/homebrew/bin/python3 tests/smoke/ui_col_discoverability.py --tag before
    /opt/homebrew/bin/python3 tests/smoke/ui_col_discoverability.py --tag after
退出码：0 = 该 tag 的全部断言成立；1 = 有断言不成立；2 = ENV（站点/浏览器起不来）
"""
import argparse
import datetime
import hashlib
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get('COL_BASE', 'http://localhost:8069')
DB = os.environ.get('EDU_DB_NAME', 'edu19')
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTROOT = os.path.join(REPO, 'tests', 'smoke', 'out_col_discoverability')

# 动作 id（本机实测：edu_portal.action_edu_fee_bill=720 / action_edu_notice_admin=756）
ACTION_FEE_BILL = 720
ACTION_NOTICE = 756

# 屏幕截断常量：列设置菜单的齿轮按钮（list_renderer.xml:49-85）
GEAR = '.o_optional_columns_dropdown_toggle'
MENU_BOX = '.o-dropdown--menu'

RESULTS = []


def check(no, name, ok, detail=''):
    RESULTS.append({'no': no, 'name': name, 'pass': bool(ok), 'detail': str(detail)[:800]})
    print('  [%s] %-4s %s%s' % ('PASS' if ok else 'FAIL', no, name,
                                (' | ' + str(detail)[:400]) if detail else ''))
    return bool(ok)


def login(page, user, pw):
    page.goto(BASE + '/web/login?db=' + DB, wait_until='domcontentloaded', timeout=60000)
    page.wait_for_selector('input[name="login"]', timeout=30000)
    page.fill('input[name="login"]', user)
    page.fill('input[name="password"]', pw)
    page.click('.oe_login_buttons button[type="submit"]', timeout=30000)
    page.wait_for_load_state('domcontentloaded', timeout=60000)
    page.wait_for_timeout(2500)


def open_action(page, action_id):
    page.goto(BASE + '/odoo/action-%d' % action_id, wait_until='domcontentloaded', timeout=60000)
    page.wait_for_selector('.o_list_view', timeout=60000)
    page.wait_for_timeout(2000)


def read_columns(page, shot=None):
    """返回 (默认渲染的列名, 列设置菜单里的列名)。

    shot 给了就在**菜单打开的状态下**截图（列设置里到底能勾到哪些列，是本次判定的
    关键证据 —— 只截关闭状态的表头证明不了「币种进没进菜单」）。
    """
    heads = page.eval_on_selector_all(
        'th[data-name]', 'els => els.map(e => e.getAttribute("data-name"))')
    menu = []
    gear = page.query_selector(GEAR)
    gear_found = bool(gear)
    if gear:
        gear.click()
        page.wait_for_timeout(900)
        menu = page.eval_on_selector_all(
            MENU_BOX + ' input[type=checkbox]', 'els => els.map(e => e.getAttribute("name"))')
        menu_labels = page.eval_on_selector_all(
            MENU_BOX + ' .dropdown-item',
            r'els => els.map(e => (e.innerText || "").replace(/\s+/g, " ").trim())')
        if shot:
            page.screenshot(path=shot, full_page=True)
        print('  [INFO] 列设置菜单（中文标签）= %s' % json.dumps(menu_labels, ensure_ascii=False))
        page.keyboard.press('Escape')
        page.wait_for_timeout(400)
    return heads, menu, gear_found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', required=True, choices=['before', 'after'])
    args = ap.parse_args()
    tag = args.tag
    outdir = os.path.join(OUTROOT, tag)
    os.makedirs(outdir, exist_ok=True)

    rc = 0
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:                                   # 量具起不来 = ENV
            print('ENV: 浏览器起不来：%s' % e)
            return 2
        ctx = browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = ctx.new_page()

        # ---------------- 0 登录 ----------------
        login(page, 'backoffice@local', 'demo123')
        check(0, '教务账号登录成功（落到后台 /apps）', '/apps' in page.url or '/odoo' in page.url, page.url)

        # ---------------- 1 财务账单列表：默认列 + 列设置菜单 ----------------
        open_action(page, ACTION_FEE_BILL)
        page.screenshot(path=os.path.join(outdir, 'fee_bill_list.png'), full_page=True)
        heads, menu, gear_found = read_columns(
            page, shot=os.path.join(outdir, 'fee_bill_list_columns_menu.png'))
        ls_keys = page.evaluate(
            "() => Object.keys(window.localStorage).filter(k => k.indexOf('optional') >= 0)")
        # 金额格的渲染文本（顺带取证：Monetary 列自带币种符号）
        amounts = page.eval_on_selector_all(
            'td[name=amount]', 'els => els.map(e => (e.innerText || "").trim())')
        # 默认可见列变多的代价读数（如实记录；不设阈值断言 —— 设了就等于把
        # 屏宽问题藏进绿灯里，宁可把原始像素数写进读数让人自己看）
        width = page.evaluate(
            """() => { const r = document.querySelector('.o_list_renderer');
                        const t = document.querySelector('.o_list_table');
                        return {renderer_client: r ? r.clientWidth : null,
                                renderer_scroll: r ? r.scrollWidth : null,
                                table_offset: t ? t.offsetWidth : null,
                                doc_scroll: document.documentElement.scrollWidth,
                                doc_client: document.documentElement.clientWidth}; }""")
        print('  [INFO] 表格宽度读数 = %s' % json.dumps(width, ensure_ascii=False))

        print('  [INFO] 默认渲染的列 th[data-name] = %s' % json.dumps(heads, ensure_ascii=False))
        print('  [INFO] 列设置菜单 = %s（齿轮按钮存在=%s）' % (
            json.dumps(menu, ensure_ascii=False), gear_found))
        print('  [INFO] localStorage optional 键 = %s' % json.dumps(ls_keys, ensure_ascii=False))
        print('  [INFO] 金额格渲染文本 = %s' % json.dumps(amounts, ensure_ascii=False))

        check(1, '读到的确是「默认值」而不是上次偏好（localStorage 无 optional_fields 记录）',
              ls_keys == [], json.dumps(ls_keys, ensure_ascii=False))
        check(2, '列设置齿轮按钮存在（有 optional 列才渲染）', gear_found, GEAR)
        check(3, '金额列自带币种符号（⇒ 单独「币种」列在默认视图里冗余）',
              bool(amounts) and any(('¥' in a or 'CNY' in a or '$' in a) for a in amounts),
              json.dumps(amounts, ensure_ascii=False)[:200])

        # ---- 1b 「默认列变多」的代价：同一构建、同一屏宽，把两列用列设置关掉再量一次 ----
        # 这是**真实 UI 操作**（点列设置里的勾选框），不是伪造 localStorage；
        # 关掉 faculty_id + reimburse_ref 后看到的就是改动前的默认视图。
        def measure():
            return page.evaluate(
                """() => { const r = document.querySelector('.o_list_renderer');
                            const t = document.querySelector('.o_list_table');
                            return {renderer_client: r ? r.clientWidth : null,
                                    renderer_scroll: r ? r.scrollWidth : null,
                                    table_offset: t ? t.offsetWidth : null,
                                    cols: document.querySelectorAll('th[data-name]').length}; }""")

        w_default = measure()

        def toggle(name):
            page.query_selector(GEAR).click()
            page.wait_for_timeout(700)
            page.click(MENU_BOX + ' input[name="%s"]' % name)
            page.wait_for_timeout(1200)
            page.keyboard.press('Escape')
            page.wait_for_timeout(600)

        toggle('faculty_id')
        toggle('reimburse_ref')
        page.wait_for_timeout(800)
        w_hidden = measure()
        page.screenshot(path=os.path.join(outdir, 'fee_bill_list_two_cols_off.png'), full_page=True)
        # 还原（不把偏好留给下一次读数）
        toggle('faculty_id')
        toggle('reimburse_ref')
        page.wait_for_timeout(900)
        w_restored = measure()
        ls_after = page.evaluate(
            "() => Object.keys(window.localStorage).filter(k => k.indexOf('optional') >= 0)")
        print('  [INFO] 宽度对照：默认(%d 列)=%s / 关掉教师+报销单号(%d 列)=%s / 还原后=%s' % (
            w_default['cols'], json.dumps(w_default), w_hidden['cols'], json.dumps(w_hidden),
            json.dumps(w_restored)))
        print('  [INFO] 还原后 localStorage optional 键 = %s' % json.dumps(ls_after, ensure_ascii=False))
        check(12, '列设置勾选真的能开关列（左侧：关→列数减少）',
              w_hidden['cols'] == w_default['cols'] - 2,
              '默认 %d 列 → 关两列 %d 列' % (w_default['cols'], w_hidden['cols']))
        check(13, '两列默认可见不会把表格挤出容器（1440px 下 renderer 无横向溢出）',
              w_default['renderer_scroll'] <= w_default['renderer_client'] + 8,
              'scroll=%s client=%s' % (w_default['renderer_scroll'], w_default['renderer_client']))

        if tag == 'before':
            # 改动前的存量事实（不是「期望」，是取证）
            check(4, '改前：教师(faculty_id) 默认看不见', 'faculty_id' not in heads, json.dumps(heads, ensure_ascii=False))
            check(5, '改前：报销单号(reimburse_ref) 默认看不见', 'reimburse_ref' not in heads, json.dumps(heads, ensure_ascii=False))
            check(6, '改前：币种(currency_id) 连列设置菜单都进不去（永久不可发现 = D1 缺陷）',
                  'currency_id' not in heads and 'currency_id' not in menu,
                  'th 命中=%s / menu 命中=%s' % ('currency_id' in heads, 'currency_id' in menu))
            check(7, '改前：教师/报销单号在列设置菜单里（有找回路径，但需用户先知道去点）',
                  'faculty_id' in menu and 'reimburse_ref' in menu, json.dumps(menu, ensure_ascii=False))
        else:
            # 改动后的验收判据（这是门禁口径）
            check(4, '改后：教师(faculty_id) 默认可发现',
                  'faculty_id' in heads, json.dumps(heads, ensure_ascii=False))
            check(5, '改后：报销单号(reimburse_ref) 默认可发现',
                  'reimburse_ref' in heads, json.dumps(heads, ensure_ascii=False))
            check(6, '改后：币种(currency_id) 默认仍不显示（保留设计），但已进列设置菜单（找回路径恢复）',
                  'currency_id' not in heads and 'currency_id' in menu,
                  'th 命中=%s / menu 命中=%s' % ('currency_id' in heads, 'currency_id' in menu))
            check(7, '改后：列设置菜单含全部 6 个可选列（学生/教师/分类/报销单号/报销状态/币种）',
                  set(menu) >= {'student_id', 'faculty_id', 'category_id',
                                'reimburse_ref', 'reimburse_state', 'currency_id'},
                  json.dumps(menu, ensure_ascii=False))

        # ---------------- 2 布告栏列表：保留 column_invisible 的反面对照 ----------------
        # 该列表的动作 domain=[('active','=',True)] ⇒ active 列恒为常量；
        # column_invisible 在此处是**有意**的技术字段隐藏（判定见通知/评审文档）。
        open_action(page, ACTION_NOTICE)
        n_heads, n_menu, n_gear = read_columns(page)
        page.screenshot(path=os.path.join(outdir, 'notice_list.png'), full_page=True)
        print('  [INFO] 布告栏默认列 = %s / 菜单 = %s' % (
            json.dumps(n_heads, ensure_ascii=False), json.dumps(n_menu, ensure_ascii=False)))
        check(8, '对照：布告栏 active 列既不进默认列、也不进菜单（本次有意保留，理由见视图注释）',
              'active' not in n_heads and 'active' not in n_menu,
              'th=%s menu=%s' % ('active' in n_heads, 'active' in n_menu))

        # ---------------- 3 命令面板（Ctrl+K 告知的事实依据） ----------------
        page.goto(BASE + '/odoo/action-%d' % ACTION_FEE_BILL,
                  wait_until='domcontentloaded', timeout=60000)
        page.wait_for_selector('.o_list_view', timeout=60000)
        page.wait_for_timeout(1500)
        page.mouse.click(700, 520)                     # 把焦点交给页面，避开搜索框
        page.wait_for_timeout(400)
        page.keyboard.press('Meta+k')                  # macOS：Odoo 的 control+k == ⌘K
        page.wait_for_timeout(2000)
        palette = bool(page.query_selector('.o_command_palette'))
        page.screenshot(path=os.path.join(outdir, 'palette_cmdk.png'), full_page=True)
        rows = []
        if palette:
            inp = page.query_selector('.o_command_palette input')
            inp.type('/报销', delay=80)
            page.wait_for_timeout(1800)
            page.screenshot(path=os.path.join(outdir, 'palette_slash_报销.png'), full_page=True)
            rows = page.eval_on_selector_all(
                '.o_command_palette .o_command',
                r'els => els.map(e => (e.innerText || "").replace(/\s+/g, " ").trim())')
        print('  [INFO] ⌘K 打开命令面板 = %s；输入 /报销 的命中 = %s' % (
            palette, json.dumps(rows, ensure_ascii=False)))
        check(9, '命令面板可开（macOS = ⌘K）', palette, 'palette=%s' % palette)
        check(10, '面板内 / + 关键字 模糊搜全部菜单（实测 /报销 → 直达报销审批）',
              any('报销审批' in r for r in rows), json.dumps(rows, ensure_ascii=False)[:300])
        # 反面对照：物理 Control+K 在 macOS 上打不开面板（Odoo 把物理 Ctrl 当作 logical alt）
        page.keyboard.press('Escape')
        page.wait_for_timeout(600)
        page.mouse.click(700, 520)
        page.wait_for_timeout(300)
        page.keyboard.press('Control+k')
        page.wait_for_timeout(1500)
        ctrlk = bool(page.query_selector('.o_command_palette'))
        check(11, '反面对照：macOS 上物理 Ctrl+K 不打开面板（⇒ 文案必须写 ⌘K/Ctrl+K 双写）',
              not ctrlk, 'ctrl+k 打开=%s' % ctrlk)

        ctx.close()
        browser.close()

    if any(not r['pass'] for r in RESULTS):
        rc = 1
    stamp = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    with open(os.path.abspath(__file__), 'rb') as fh:
        script_md5 = hashlib.md5(fh.read()).hexdigest()[:8]
    payload = {'tag': tag, 'base': BASE, 'db': DB, 'stamp': stamp,
               'script': os.path.basename(__file__), 'script_md5': script_md5,
               'viewport': {'w': 1440, 'h': 1000}, 'results': RESULTS,
               'passed': sum(1 for r in RESULTS if r['pass']), 'total': len(RESULTS)}
    with open(os.path.join(outdir, 'results.json'), 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print('  [%s] %d/%d 通过 · 读数 %s' % (
        'OK' if rc == 0 else 'FAIL', payload['passed'], payload['total'], stamp))
    print('  证据目录：%s' % outdir)
    return rc


if __name__ == '__main__':
    sys.exit(main())
