#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""候选修法验证器（**内存实验，不改仓库任何文件**）：给列表选择框的 label 补 .visually-hidden 文字。

## 它验什么（**双向**，自己给自己造反例）

edu_brand 对 web.ListRenderer / web.ListRenderer.RecordRow 的 CheckBox 用法补了 slot 文字
（slot → label → input 有可访问名）。本脚本在**浏览器内存里**把这件事做两遍：

  ① **反向注入**：先把 label 内容清空（= 修复前状态）⇒ axe 必须报出违规；
     若报 0，说明这把尺子看不到缺陷 ⇒ 本脚本 FAIL（量具不灵）。
  ② **修补**：再把 .visually-hidden 文字补回去 ⇒ axe 与 AX 树都必须归 0。
  ③ **口径演示**：缺陷状态下顺带量一次大视口（2700px）——同一页报出的条数会变
     （900px vs 2700px），命中集合是 DOM 顺序的前缀。这正是"axe 报的条数不等于缺陷面"的实证。

两把尺子同时用：axe（门禁那把）+ 浏览器 AX 树（CDP，独立量具，见 a11y_ax_tree_probe.py）。

## 跑法

    python3 tests/smoke/a11y_label_fix_experiment.py
    python3 tests/smoke/a11y_label_fix_experiment.py --skip-strip --dump   # 只跑修补那一半

## 退出码

0 = 通过 ｜ 1 = **判据失败**（量具看不到缺陷 / 修补后仍有违规 / AX 树仍有匿名控件）｜ 2 = ENV
（升级锁 / 站点不可达 / axe 取不到且无缓存 / 浏览器起不来）—— ENV 不当通过。

## 自清

**只读 + 只在内存里改 DOM**：不动数据库、不动仓库文件、不建夹具；浏览器上下文用完即关。
axe 优先用本地缓存（tempdir/edu_axe/axe-<版本>.min.js），缺则从 CDN 取一次（扫描本身不需要联网）。
"""
import argparse
import glob
import os
import sys

import requests

BASE = 'http://localhost:8069'
DB = 'edu19'
LOGIN = ('backoffice@local', 'demo123')
AXE_URL = 'https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js'

AXE_JS = """() => axe.run(document, {resultTypes: ['violations'],
    runOnly: {type: 'rule', values: ['label']}}).then(r => {
  const v = (r.violations.find(x => x.id === 'label') || {nodes: []}).nodes;
  return {count: v.length, targets: v.map(n => n.target.join(' '))};
})"""

STRIP_JS = """() => {   // 反向注入：清空选择框 label 的内容 = 修复前状态
  let n = 0;
  document.querySelectorAll('.o_list_record_selector label.form-check-label').forEach((lab) => {
    if (!lab.textContent.trim()) return;
    lab.textContent = ''; n++;
  });
  return n;
}"""

PATCH_JS = """() => {   // 修补：补 .visually-hidden slot 文字
  let n = 0;
  document.querySelectorAll('.o_list_record_selector label.form-check-label').forEach((lab) => {
    if (lab.textContent.trim()) return;
    const s = document.createElement('span');
    s.className = 'visually-hidden';
    s.textContent = lab.closest('thead') ? '全选本页' : '选择本行';
    lab.appendChild(s); n++;
  });
  return n;
}"""


def axe_source():
    cache = glob.glob(os.path.join(os.environ.get('TMPDIR') or '/tmp',
                                   'edu_axe', 'axe-*.min.js'))
    if cache:
        return open(cache[0], encoding='utf-8').read(), 'cache:%s' % cache[0]
    try:
        r = requests.get(AXE_URL, timeout=25)
        if r.status_code == 200 and len(r.content) > 100000:
            return r.text, 'cdn:%s' % AXE_URL
    except Exception as exc:
        return None, 'ERR %s' % str(exc)[:80]
    return None, 'HTTP %s' % r.status_code


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


def ax_checkboxes(ctx, pg):
    """浏览器自己的 AX 树里 checkbox 的 (总数, 匿名数)。"""
    cdp = ctx.new_cdp_session(pg)
    cdp.send('Accessibility.enable')
    tree = cdp.send('Accessibility.getFullAXTree')
    boxes = [(n.get('name') or {}).get('value') or '' for n in tree.get('nodes', [])
             if ((n.get('role') or {}).get('value')) == 'checkbox']
    return len(boxes), len([x for x in boxes if not x.strip()])


def load(b, cookies, path, height, axe):
    ctx = b.new_context(viewport={'width': 1280, 'height': height}, locale='zh-CN')
    ctx.add_cookies(cookies)
    pg = ctx.new_page()
    pg.goto(BASE + path, wait_until='domcontentloaded', timeout=90000)
    pg.wait_for_selector('.o_navbar', timeout=25000)
    pg.wait_for_timeout(3000)
    pg.add_script_tag(content=axe)
    return ctx, pg


def main():
    ap = argparse.ArgumentParser(description='候选修法验证器（内存实验，含反向注入）')
    ap.add_argument('--path', default='/odoo/contacts')
    ap.add_argument('--dump', action='store_true')
    ap.add_argument('--skip-strip', action='store_true',
                    help='跳过反向注入（默认会先清空 label，验量具看得到缺陷）')
    args = ap.parse_args()

    pre = preflight()
    if isinstance(pre, str):
        print('ENV：%s ⇒ 本轮作废' % pre)
        return 2
    cookies = pre
    axe, where = axe_source()
    if axe is None:
        print('ENV：axe-core 取不到（%s）⇒ 本轮作废' % where)
        return 2
    print('axe 来源：%s' % where)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print('ENV：playwright 不可用：%s' % exc)
        return 2

    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(channel='chrome', headless=True, args=['--no-proxy-server'])
            ctx, pg = load(b, cookies, args.path, 900, axe)
            # ⚠ 三段必须在**同一个页面**里做：换页面就等于换夹具，测不到"注入 → 修补"的因果
            baseline = pg.evaluate(AXE_JS)
            ax_baseline = ax_checkboxes(ctx, pg)
            stripped = pg.evaluate(STRIP_JS) if not args.skip_strip else 0
            pg.wait_for_timeout(400)
            injected = pg.evaluate(AXE_JS)
            ax_injected = ax_checkboxes(ctx, pg)
            if not args.skip_strip:            # 口径演示：同一页、只改视口
                pg.set_viewport_size({"width": 1280, "height": 2700})
                pg.wait_for_timeout(600)
                injected_tall = pg.evaluate(AXE_JS)
                pg.set_viewport_size({"width": 1280, "height": 900})
                pg.wait_for_timeout(400)
            else:
                injected_tall = {"count": baseline["count"], "targets": []}
            patched = pg.evaluate(PATCH_JS)
            pg.wait_for_timeout(400)
            fixed = pg.evaluate(AXE_JS)
            ax_fixed = ax_checkboxes(ctx, pg)
            ctx.close()
            b.close()
    except Exception as exc:
        print('ENV：量不到（%s）' % str(exc)[:120])
        return 2

    print('== %s' % args.path)
    print('   ⓪ 线上实况（未注入）            axe label 违规 = %d 条 ｜ AX 树 checkbox %d / 匿名 %d'
          % (baseline['count'], ax_baseline[0], ax_baseline[1]))
    print('   ① 反向注入（清空 %d 个 label）  axe label 违规 = **%d** 条 ｜ AX 树匿名 %d 个'
          % (stripped, injected['count'], ax_injected[1]))
    print('   ② 口径演示（同页只放到 2700px） axe label 违规 = **%d** 条'
          '  ← 与①的差值就是"读数随视口走、命中是前缀"的实证' % injected_tall['count'])
    print('   ③ 修补（补 %d 个 .visually-hidden）axe label 违规 = **%d** 条 ｜ AX 树匿名 **%d** 个'
          % (patched, fixed['count'], ax_fixed[1]))
    if args.dump:
        print('   注入后命中（前 8）：%s' % injected['targets'][:8])
        print('   大视口命中（前 8）：%s' % injected_tall['targets'][:8])

    fails = []
    if not args.skip_strip:
        if stripped == 0:
            fails.append('夹具失败：没有 label 可清空（页面结构变了？）')
        elif injected['count'] == 0:
            fails.append('量具不灵：清空 label 后 axe 仍报 0 条 —— 这把尺子看不到缺陷')
    if fixed['count'] != 0:
        fails.append('候选修法无效：修补后 axe 仍报 %d 条' % fixed['count'])
    if ax_fixed[1] != 0:
        fails.append('修补后 AX 树里仍有 %d 个匿名 checkbox' % ax_fixed[1])
    if fails:
        print('RESULT=FAIL')
        for f in fails:
            print('  - %s' % f)
        return 1
    print('RESULT=OK：量具看得到缺陷（注入 %d 条），修补后 axe=%d、AX 树匿名=%d（双向证明成立）'
          % (injected['count'], fixed['count'], ax_fixed[1]))
    return 0


if __name__ == '__main__':
    sys.exit(main())