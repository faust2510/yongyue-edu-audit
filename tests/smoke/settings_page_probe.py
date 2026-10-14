#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""settings_page_probe.py —— /odoo/settings 的真浏览器量具（Playwright）。

为什么不能只看 HTTP 状态码
  /odoo/settings 是 SPA 外壳：**服务端炸了也回 200**（本 bug 就是这么藏住的）。
  故障态实测：http=200，但页面渲染出 Odoo 错误弹窗、没有任何字段。
  所以本量具的判据全部落在**渲染结果**与**保存往返**上。

模式
  rpc       : 直打设置页服务端真走的 RPC（default_get 全字段 + **客户端原样载荷**的
              onchange）—— 红/绿最灵敏，不依赖 DOM。
  open      : 真打开 /odoo/settings，报渲染出的字段、控件读数、错误弹窗。
  roundtrip : 改**两个**截止日 → 保存 → 重新加载 → 比对（屏幕上 + ir.config_parameter
              + **两个消费页**），随后还原原值。端到端判据：
              「设置表单改的值 = 落库的值 = 公开页/报课页显示的值」。
  save-noop : 不动字段直接保存（控制组）：必须无错，且本模块与**无关**配置项一字不变。

机制备忘（Odoo 19 实测，写清是为了让下一个人不必再摸一遍）
  · 日期字段是 <button> 形态：点一下变 <input>，填 'YYYY/MM/DD HH:MM:SS' 再回车。
    value/tooltip 的日期是**用户时区**下的读数（视图 options show_time=False 只显示日期）。
  · 设置页保存 = call_kw/web_save **+ call_button/execute**（execute 才落
    ir.config_parameter）。视图缺 js_class="base_settings" 时只有 web_save —— 改了不落库
    （实测：参数一字不变、刷新回旧值）。
  · /odoo/settings 打开的是 action 86（path=settings），它的 view_id 为空 ⇒ 用
    res.config.settings 的**默认主表单视图**；ir.ui.view._order='priority,name,id' ⇒
    'res.config.settings.form.edu.deadline' 排在 'res.config.settings.view.form' 之前，
    于是**设置页渲染的就是本模块这张表单**（这也是它一炸就整页打不开的原因）。

消费方键位（别弄混）
  /admissions       ← edu.apply.deadline（报名截止，edu_brand/views/pages.xml:324）
  /subject/enroll   ← edu.enroll.deadline（报课截止，edu_portal/controllers/enroll.py:208）

用法
  python3 tests/smoke/settings_page_probe.py --mode open --out /tmp/open.json
  python3 tests/smoke/settings_page_probe.py --mode rpc
  python3 tests/smoke/settings_page_probe.py --mode roundtrip --new-date 2026-11-15
  python3 tests/smoke/settings_page_probe.py --mode save-noop
退出码：0=绿 ｜ 1=红 ｜ 2=ENV（站点不可达/登录失败/控件找不到）
"""
import argparse
import json
import re
import sys

BASE_DEFAULT = 'http://127.0.0.1:8069'
ERR_MARKS = ['出了点问题', 'Odoo Server Error', '无法完成该操作',
             'Traceback (most recent call last)', 'must have type']
# (表单字段名, ir.config_parameter 键, 消费该键的页面, 该页上的锚句)
FIELDS = [
    ('edu_apply_deadline', 'edu.apply.deadline', '/admissions', '报名截止日期为'),
    ('edu_enroll_deadline', 'edu.enroll.deadline', '/subject/enroll', '本轮报课截止'),
]
CN_DATE = re.compile(r'\d{4}\u5e74\d{1,2}\u6708\d{1,2}\u65e5')
APPLY_FIELD = FIELDS[0][0]


def cn_of(iso_date):
    y, m, d = iso_date.split('-')
    return '%d\u5e74%d\u6708%d\u65e5' % (int(y), int(m), int(d))


def login(ctx, base, user, pwd, db):
    r = ctx.request.post(base + '/web/session/authenticate',
                         data=json.dumps({'jsonrpc': '2.0', 'params': {
                             'db': db, 'login': user, 'password': pwd}}),
                         headers={'Content-Type': 'application/json'})
    uid = (r.json().get('result') or {}).get('uid')
    return uid, (None if uid else 'login %s 失败' % user)


def call_kw(ctx, base, model, method, args, kwargs=None):
    return ctx.request.post(base + '/web/dataset/call_kw', data=json.dumps({
        'jsonrpc': '2.0', 'method': 'call',
        'params': {'model': model, 'method': method, 'args': args,
                   'kwargs': kwargs or {}}}),
        headers={'Content-Type': 'application/json'}).json()


def read_param(ctx, base, key):
    r = call_kw(ctx, base, 'ir.config_parameter', 'get_param', [key])
    if 'result' in r:
        return r['result']
    r2 = call_kw(ctx, base, 'ir.config_parameter', 'search_read',
                 [[['key', '=', key]], ['value']])
    if 'result' in r2 and r2['result']:
        return r2['result'][0]['value']
    return '<读取失败: %s>' % json.dumps(r, ensure_ascii=False)[:150]


def dialog_text(page):
    for sel in ('.o_dialog', '.modal.show', '[role="alertdialog"]'):
        try:
            n = page.locator(sel)
            if n.count():
                t = n.first.inner_text().strip()
                if t:
                    return t
        except Exception:
            pass
    try:
        txt = page.inner_text('body')
    except Exception:
        return ''
    for m in ERR_MARKS:
        if m in txt:
            i = txt.find(m)
            return txt[max(0, i - 100): i + 300]
    return ''


def field_state(page, name=APPLY_FIELD):
    js = ("() => {const w=document.querySelector('.o_field_widget[name=\"" + name + "\"]');"
          " if (!w) return null; const e=w.querySelector('button,input');"
          " return {tag: e.tagName, value: (e.getAttribute('value')||e.value||''),"
          " shown: (e.innerText||'').trim(), tooltip: e.getAttribute('data-tooltip')||'',"
          " form_cls: (document.querySelector('.o_form_view')||{}).className};}")
    return page.evaluate(js)


def wait_form(page, base, path, timeout=60000):
    page.goto(base + path, wait_until='domcontentloaded')
    page.wait_for_selector('.o_form_view.oe_form_configuration', timeout=timeout)
    page.wait_for_selector('.o_field_widget[name="%s"] button' % APPLY_FIELD, timeout=timeout)


def set_date(page, iso_date, name=APPLY_FIELD):
    page.locator('.o_field_widget[name="%s"] button' % name).first.click()
    page.wait_for_timeout(600)
    inp = page.locator('.o_field_widget[name="%s"] input' % name).first
    inp.fill(iso_date.replace('-', '/') + ' 00:00:00')
    inp.press('Enter')
    page.wait_for_timeout(900)
    # 鼠标移开：控件悬停时的 tooltip <span> 会盖住下一个字段，导致 click 被拦截
    page.mouse.move(4, 4)
    page.wait_for_timeout(600)


def save(page):
    page.locator('button.o_form_button_save').first.click()
    page.wait_for_timeout(4000)


def consumer_date(br, base, db, path, anchor):
    if path == '/subject/enroll':
        sctx = br.new_context()
        login(sctx, base, 'stu@local', 'demo123', db)
    else:
        sctx = br.new_context()
    r = sctx.request.get(base + path)
    text = r.text()
    sctx.close()
    for m in re.finditer(re.escape(anchor), text):
        found = CN_DATE.findall(text[m.end(): m.end() + 90])
        if found:
            return {'status': r.status, 'date': found[0]}
    return {'status': r.status, 'date': ''}


def consumers(br, base, db):
    return {path: consumer_date(br, base, db, path, anchor)
            for _f, _k, path, anchor in FIELDS}


def mode_rpc(ctx, base, args, out):
    names = sorted((call_kw(ctx, base, 'res.config.settings', 'fields_get', [],
                            {'attributes': ['type']}).get('result') or {}).keys())
    dg = call_kw(ctx, base, 'res.config.settings', 'default_get', [names])
    out['default_get'] = {
        'ok': 'result' in dg,
        'error': json.dumps(dg.get('error', {}), ensure_ascii=False)[:300],
        'deadline': {f: (dg.get('result') or {}).get(f) for f, _k, _p, _a in FIELDS}
        if 'result' in dg else None}
    # 客户端原样载荷（真浏览器抓下来的；onchange 首调内部会走 default_get）
    oc = call_kw(ctx, base, 'res.config.settings', 'onchange',
                 [[], {}, [], {f: {} for f, _k, _p, _a in FIELDS} | {'display_name': {}}])
    out['onchange'] = {'ok': 'result' in oc,
                       'error': json.dumps(oc.get('error', {}), ensure_ascii=False)[:300]}
    out['params'] = {k: read_param(ctx, base, k) for _f, k, _p, _a in FIELDS}
    ok = out['default_get']['ok'] and out['onchange']['ok']
    out['verdict'] = 'PASS' if ok else 'FAIL'
    print('%s rpc: fields=%d default_get=%s onchange=%s params=%s'
          % (out['verdict'], len(names), out['default_get']['error'] or 'OK',
             out['onchange']['error'] or 'OK', out['params']))
    return 0 if ok else 1


def mode_open(page, ctx, base, args, out):
    wait_form(page, base, args.path)
    page.wait_for_timeout(2000)
    st = field_state(page)
    out['dialog'] = dialog_text(page)[:600]
    out['field'] = st
    out['fields_on_page'] = page.evaluate(
        "() => [...document.querySelectorAll('.o_field_widget')].map(e => e.getAttribute('name'))")
    out['form_is_settings_view'] = bool(st and 'o_base_settings_view' in st.get('form_cls', ''))
    out['text_head'] = ' | '.join(
        page.inner_text('.o_action_manager').split('\n'))[:400] if page.locator('.o_action_manager').count() else ''
    ok = bool(st) and not out['dialog'] and APPLY_FIELD in out['fields_on_page'] \
        and out['form_is_settings_view']
    out['verdict'] = 'PASS' if ok else 'FAIL'
    print('%s open %s: field=%s settings_view=%s dialog=%r'
          % (out['verdict'], args.path, json.dumps(st, ensure_ascii=False),
             out['form_is_settings_view'], out['dialog'][:120]))
    return 0 if ok else 1


def mode_roundtrip(page, ctx, base, args, out, br=None):
    """改两个截止日 → 保存 → 重载 → 两个消费页 → 还原。"""
    wait_form(page, base, args.path)
    page.wait_for_timeout(1500)
    out['before'] = {'ui': {f: field_state(page, f) for f, _k, _p, _a in FIELDS},
                     'params': {k: read_param(ctx, base, k) for _f, k, _p, _a in FIELDS},
                     'consumers': consumers(br, base, args.db)}
    for f, _k, _p, _a in FIELDS:
        set_date(page, args.new_date, f)
    out['typed'] = {f: field_state(page, f) for f, _k, _p, _a in FIELDS}
    save(page)
    out['save_dialog'] = dialog_text(page)[:400]
    out['params_after_save'] = {k: read_param(ctx, base, k) for _f, k, _p, _a in FIELDS}
    out['consumers_after_save'] = consumers(br, base, args.db)   # 必须在还原**之前**抓
    wait_form(page, base, args.path)
    page.wait_for_timeout(1500)
    out['ui_after_reload'] = {f: field_state(page, f) for f, _k, _p, _a in FIELDS}
    out['reload_dialog'] = dialog_text(page)[:400]
    # 还原
    for f, _k, _p, _a in FIELDS:
        set_date(page, args.restore_date, f)
    save(page)
    out['params_restored'] = {k: read_param(ctx, base, k) for _f, k, _p, _a in FIELDS}
    wait_form(page, base, args.path)
    page.wait_for_timeout(1200)
    out['ui_restored'] = {f: field_state(page, f) for f, _k, _p, _a in FIELDS}
    out['consumers_restored'] = consumers(br, base, args.db)

    ok = (not out['save_dialog'] and not out['reload_dialog'])
    for f, k, path, _a in FIELDS:
        ok = ok and out['params_after_save'][k] == args.new_date
        ok = ok and args.new_date.replace('-', '/') in (out['ui_after_reload'][f] or {}).get('value', '')
        ok = ok and out['params_restored'][k] == out['before']['params'][k]
        ok = ok and args.restore_date.replace('-', '/') in (out['ui_restored'][f] or {}).get('value', '')
        ok = ok and out['consumers_after_save'][path]['status'] == 200 \
            and out['consumers_after_save'][path]['date'] == cn_of(args.new_date)
        ok = ok and out['consumers_restored'][path]['status'] == 200 \
            and out['consumers_restored'][path]['date'] == cn_of(args.restore_date)
    out['verdict'] = 'PASS' if ok else 'FAIL'
    print('%s roundtrip: 参数 保存后=%s 还原后=%s'
          % (out['verdict'], out['params_after_save'], out['params_restored']))
    print('  UI 重载后=%s' % json.dumps(out['ui_after_reload'], ensure_ascii=False))
    print('  消费方 保存后=%s' % json.dumps(out['consumers_after_save'], ensure_ascii=False))
    print('  消费方 还原后=%s' % json.dumps(out['consumers_restored'], ensure_ascii=False))
    for key in ('save_dialog', 'reload_dialog'):
        if out[key]:
            print('  DIALOG(%s)=%r' % (key, out[key][:200]))
    return 0 if ok else 1


def mode_save_noop(page, ctx, base, args, out):
    """控制组：不动字段直接保存，本模块与无关配置项都必须一字不变。"""
    wait_form(page, base, args.path)
    page.wait_for_timeout(1500)
    keys = [k for _f, k, _p, _a in FIELDS]
    ctrl_keys = ['web.base.url', 'recaptcha_min_score', 'product.weight_in_lbs']
    before = {k: read_param(ctx, base, k) for k in keys + ctrl_keys}
    save(page)
    out['dialog'] = dialog_text(page)[:400]
    after = {k: read_param(ctx, base, k) for k in keys + ctrl_keys}
    out['before'], out['after'] = before, after
    ok = (not out['dialog']) and before == after
    out['verdict'] = 'PASS' if ok else 'FAIL'
    print('%s save-noop: %s -> %s (dialog=%r)'
          % (out['verdict'], before, after, out['dialog'][:80]))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description='/odoo/settings 打开/保存 真浏览器量具')
    ap.add_argument('--mode', choices=['open', 'rpc', 'roundtrip', 'save-noop'], required=True)
    ap.add_argument('--base-url', default=BASE_DEFAULT)
    ap.add_argument('--db', default='edu19')
    ap.add_argument('--login-user', default='admin')
    ap.add_argument('--login-pass', default='demo123')
    ap.add_argument('--path', default='/odoo/settings')
    ap.add_argument('--new-date', default='2026-11-15')
    ap.add_argument('--restore-date', default='2026-10-01')
    ap.add_argument('--no-consumer', action='store_true',
                    help='roundtrip 时不抓消费页（默认抓）')
    ap.add_argument('--out')
    args = ap.parse_args()
    args.check_consumer = not args.no_consumer
    base = args.base_url.rstrip('/')
    out = {'mode': args.mode, 'base_url': base, 'login': args.login_user}

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print('ENV: playwright 不可用（%s）' % str(e)[:120], file=sys.stderr)
        return 2
    rc = 2
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={'width': 1440, 'height': 1000})
        try:
            uid, err = login(ctx, base, args.login_user, args.login_pass, args.db)
            if err:
                print('ENV: %s' % err, file=sys.stderr)
                return 2
            out['uid'] = uid
            ctx.set_default_timeout(60000)
            page = ctx.new_page()
            try:
                if args.mode == 'rpc':
                    rc = mode_rpc(ctx, base, args, out)
                elif args.mode == 'open':
                    rc = mode_open(page, ctx, base, args, out)
                elif args.mode == 'roundtrip':
                    rc = mode_roundtrip(page, ctx, base, args, out, br)
                else:
                    rc = mode_save_noop(page, ctx, base, args, out)
            finally:
                page.close()
        finally:
            br.close()
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
        print('OUT=%s' % args.out)
    return rc


if __name__ == '__main__':
    sys.exit(main())