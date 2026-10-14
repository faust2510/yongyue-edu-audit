#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列表选择框的 **DOM 层**审计：每个表头/行选择框的 label 实体、id 唯一性、父链。

## 与 a11y_ax_tree_probe.py 的分工（两把尺子）

· a11y_ax_tree_probe.py = **浏览器算出来的可访问名**（AX 树，独立于 axe）—— 判"有没有名字"。
· 本脚本            = **我们自己的标记**（label 实体 / id / 结构）—— 判"名字是从哪来的"。
两者一起才能把"axe 报了 19 条"这类读数钉死：2026-09-29 的取证里，正是本脚本证明了
报出的 19 条与放过的 62 条**逐字段同款**（父链、空 label、id 唯一性完全一致），
从而把差异归到 axe 的读数口径（只判首屏可见行）而不是页面结构。

## 断言

每个 .o_list_record_selector 里的 label 都**非空**（修复前 81/81 全空 ⇒ FAIL；
edu_brand 补了 .visually-hidden slot 文字后应为 0 空），且每个选择框的 label 恰好 1 个。

## 跑法

    python3 tests/smoke/a11y_label_dom_compare.py                 # /odoo/contacts
    python3 tests/smoke/a11y_label_dom_compare.py --rows 5 --dump # 只打印前 5 行明细

## 退出码

0 = 通过 ｜ 1 = **判据失败**（有空 label / label 数不为 1）｜ 2 = ENV（锁 / 站点 / 登录）
## 自清

只读：会话认证 + GET，不写任何数据、不建夹具。
"""
import argparse
import os
import sys

import requests

BASE = 'http://localhost:8069'
DB = 'edu19'
LOGIN = ('backoffice@local', 'demo123')

JS = """(limit) => {
  const rows = [];
  const cells = [...document.querySelectorAll('th.o_list_record_selector, td.o_list_record_selector')];
  cells.forEach((cell, idx) => {
    const input = cell.querySelector('input[type=checkbox]');
    const labels = input && input.id
      ? [...document.querySelectorAll('label[for="' + input.id + '"]')] : [];
    const lab = labels[0] || null;
    if (idx >= limit) return;
    rows.push({idx: idx,
               where: cell.tagName === 'TH' ? 'thead' : 'row',
               input_id: input ? input.id : null,
               label_count: labels.length,
               label_text: lab ? lab.textContent : null,
               label_html: lab ? lab.outerHTML.slice(0, 110) : null,
               data_id: (cell.closest('tr') || {}).getAttribute
                        ? (cell.closest('tr') || {}).getAttribute('data-id') : null,
               parent_chain: [cell.tagName, (cell.parentElement || {}).tagName || '']});
  });
  const all = [...document.querySelectorAll('.o_list_record_selector input[type=checkbox]')];
  const empty = all.filter(i => {
    const l = i.id ? document.querySelector('label[for="' + i.id + '"]') : null;
    return !l || !l.textContent.trim();
  });
  return {total: all.length, empty_labels: empty.length, rows: rows,
          first_data_ids: [...document.querySelectorAll('tbody tr.o_data_row')]
              .slice(0, 3).map(t => t.getAttribute('data-id'))};
}"""


def lock_path():
    return os.path.join(os.environ.get('TMPDIR') or '/tmp', 'edu19_upgrade.lock')


def probe_session():
    """就绪探针专用 Session：**trust_env=False**。

    ⚠ 为什么必须（2026-09-29 实测）：macOS 的系统代理（scutil --proxy 里 HTTPProxy=127.0.0.1:12450）
    会被 module 级 requests.get 自动采用 ⇒ 探 http://localhost:8069 反而经代理拿到 **502** ⇒
    探针误报「站点未就绪」，把三把尺子整体判成 ENV（ENV 不当通过，于是三条读数一个也拿不到）。
    scripts/check_accessibility.py 的 site_ready() 早已写明这条纪律，这里补齐。
    """
    s = requests.Session()
    s.trust_env = False
    return s


def preflight():
    if os.path.isdir(lock_path()):
        return '有升级在进行（%s 存在）' % lock_path()
    try:
        r = probe_session().get(BASE + '/web/login?db=' + DB, timeout=15, allow_redirects=False)
    except Exception as exc:
        return '站点不可达：%s' % exc
    if r.status_code not in (200, 302, 303):
        return '站点未就绪（/web/login → %s）' % r.status_code
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + '/web/session/authenticate', json={'jsonrpc': '2.0', 'params': {
        'db': DB, 'login': LOGIN[0], 'password': LOGIN[1]}}, timeout=25)
    if r.status_code != 200:
        return '登录失败（HTTP %s）' % r.status_code
    return [{'name': c.name, 'value': c.value, 'domain': 'localhost',
             'path': c.path or '/'} for c in s.cookies]


def main():
    ap = argparse.ArgumentParser(description='列表选择框 DOM 层审计（label 实体/id/父链）')
    ap.add_argument('--path', default='/odoo/contacts')
    ap.add_argument('--rows', type=int, default=3, help='打印前 N 行明细')
    ap.add_argument('--dump', action='store_true', help='打印完整 JSON')
    args = ap.parse_args()

    cookies = preflight()
    if isinstance(cookies, str):
        print('ENV：%s ⇒ 本轮作废' % cookies)
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print('ENV：playwright 不可用：%s' % exc)
        return 2

    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(channel='chrome', headless=True, args=['--no-proxy-server'])
            ctx = b.new_context(viewport={'width': 1280, 'height': 900}, locale='zh-CN')
            ctx.add_cookies(cookies)
            pg = ctx.new_page()
            r = pg.goto(BASE + args.path, wait_until='domcontentloaded', timeout=90000)
            status = r.status if r else 0
            pg.wait_for_selector('.o_navbar', timeout=25000)
            pg.wait_for_timeout(3000)
            data = pg.evaluate(JS, args.rows)
            ctx.close(); b.close()
    except Exception as exc:
        print('ENV：量不到（%s）' % str(exc)[:120])
        return 2

    print('== %s ｜ HTTP %s' % (args.path, status))
    print('   选择框 %d 个 ｜ **空 label %d 个** ｜ 前3行 data-id=%s'
          % (data['total'], data['empty_labels'], data['first_data_ids']))
    for it in data['rows']:
        print('   [%s] id=%s label数=%s label文本=%r'
              % (it['where'], it['input_id'], it['label_count'], it['label_text']))
    if args.dump:
        import json
        print(json.dumps(data, ensure_ascii=False, indent=1))

    fails = []
    if status != 200:
        fails.append('HTTP %s' % status)
    if data['empty_labels']:
        fails.append('仍有 %d 个选择框的 label 为空（DOM 层）' % data['empty_labels'])
    for it in data['rows']:
        if it['label_count'] != 1:
            fails.append('%s 的 label 数 = %s（应为 1）' % (it['input_id'], it['label_count']))
    if fails:
        print('RESULT=FAIL')
        for f in fails:
            print('  - %s' % f)
        return 1
    print('RESULT=OK：%d 个选择框的 label 全部非空且一一对应' % data['total'])
    return 0


if __name__ == '__main__':
    sys.exit(main())